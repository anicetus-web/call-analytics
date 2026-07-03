"""
Telegram bot handlers (aiogram 3.x).

Commands:
  /start   — welcome message, shows which project the manager is assigned to
  /status  — show last 5 calls and their statuses
  /skip    — in WaitingComment state: upload the call without a comment

Flow:
  1. Manager sends an audio/video/voice/document message
  2. Bot shows inline keyboard: "Add comment" | "Skip"
  3. Manager picks "Add comment" → enters WaitingComment state
     OR picks "Skip" → file is uploaded immediately without comment
  4. In WaitingComment state: any text message is treated as the comment

Manager ↔ Project mapping: a manager can belong to multiple projects.
If assigned to exactly one project — that project is used automatically.
If assigned to multiple — bot asks to choose (simple inline keyboard).

All API calls go through httpx to the local FastAPI server.
"""

import logging
import os
import uuid
from html import escape as _esc
from typing import Any

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, Message, Video,
)

from bot.states import UploadFlow
from config import settings

logger = logging.getLogger(__name__)

# HTML parse mode is the default for every outgoing message from here on — any
# dynamic text interpolated into a message (filenames, project/manager names)
# MUST go through _esc() first, or a name containing "<"/"&" will make Telegram
# reject the send outright.
bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Internal API base URL — bot talks to the FastAPI server (same host by default,
# configurable so the bot can run in a separate container/process).
_API_BASE = settings.INTERNAL_API_URL.rstrip("/")
_BOT_HEADERS = {"X-Bot-Secret": settings.BOT_SECRET}
_MAX_COMMENT_LEN = 2000


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_manager_projects(telegram_id: int) -> list[dict[str, Any]] | None:
    """Return projects the manager belongs to.

    Returns:
        - list of projects (possibly empty) on success
        - None if the DB call failed (caller shows "service unavailable")

    Note: an empty list means either "manager not registered" or "registered but
    in no projects" — both surface the same "contact admin" message, so the
    bot does not need to distinguish them.
    """
    from sqlalchemy import select
    from database import User, UserRole, ProjectMember, Project, AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            # Find user by telegram_id
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id, User.role == UserRole.MANAGER)
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                return []

            # Find active projects the user is a member of
            members_result = await session.execute(
                select(ProjectMember, Project)
                .join(Project, Project.id == ProjectMember.project_id)
                .where(
                    ProjectMember.user_id == user.id,
                    Project.is_active.is_(True),
                )
            )
            return [
                {"id": project.id, "name": project.name, "user_id": user.id}
                for _, project in members_result.all()
            ]
    except Exception:
        logger.exception("DB error fetching projects for telegram_id=%d", telegram_id)
        return None


def _projects_keyboard(projects: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=p["name"], callback_data=f"project:{p['id']}")]
        for p in projects
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _comment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Добавить комментарий", callback_data="add_comment"),
        InlineKeyboardButton(text="Пропустить", callback_data="skip_comment"),
    ]])


class _FileTooLargeError(Exception):
    """Raised when Telegram refuses to hand us the file (Bot API caps downloads at 20 MB)."""


async def _upload_file(
    file_id: str,
    project_id: int,
    user_id: int,
    comment: str | None,
    original_filename: str,
) -> tuple[int | None, str | None]:
    """
    Download file from Telegram and upload to local API.
    Returns (call_id, None) on success, (None, user_facing_reason) on failure.
    """
    try:
        # Get file download URL from Telegram
        file = await bot.get_file(file_id)
    except TelegramBadRequest as exc:
        if "file is too big" in str(exc).lower():
            # The Bot API (api.telegram.org) refuses to hand over files above 20 MB,
            # regardless of our own 200 MB upload limit on the API side — a long call
            # recording routinely exceeds this. Retrying changes nothing, so tell the
            # manager clearly instead of the generic failure message.
            raise _FileTooLargeError() from exc
        logger.exception("Telegram getFile failed for %s", original_filename)
        return None, "Telegram отклонил файл. Попробуйте ещё раз."

    file_path = file.file_path
    download_url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"

    # Write to a temp file instead of buffering in memory — avoids holding 200 MB as bytes.
    tmp_path = os.path.join(settings.TEMP_DIR, f"bot_{uuid.uuid4().hex}_{original_filename}")
    os.makedirs(settings.TEMP_DIR, exist_ok=True)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("GET", download_url) as tg_response:
                tg_response.raise_for_status()
                with open(tmp_path, "wb") as f:
                    async for chunk in tg_response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

            form_data = {"project_id": str(project_id), "user_id": str(user_id)}
            if comment:
                form_data["comment"] = comment

            with open(tmp_path, "rb") as f:
                api_response = await client.post(
                    f"{_API_BASE}/api/calls/upload",
                    headers=_BOT_HEADERS,
                    data=form_data,
                    files={"file": (original_filename, f)},
                )

        if api_response.status_code == 201:
            return api_response.json()["call_id"], None
        else:
            logger.error("Upload API error %d: %s", api_response.status_code, api_response.text)
            return None, None
    except Exception:
        logger.exception("Error uploading file %s", original_filename)
        return None, None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


_SERVICE_UNAVAILABLE_MSG = "⚠️ Сервис временно недоступен, попробуйте позже."
_NOT_IN_PROJECT_MSG = (
    "👋 Добро пожаловать! Вы ещё не добавлены ни в один проект.\n"
    "Обратитесь к администратору."
)
_SESSION_EXPIRED_MSG = "⚠️ Сессия устарела — пожалуйста, отправьте файл заново."

_TOO_LARGE_MSG = (
    "❌ <b>Файл слишком большой</b>\n\n"
    "Telegram не позволяет боту скачивать файлы крупнее 20 МБ. "
    "Сожмите запись или разбейте её на части."
)
_GENERIC_FAIL_MSG = "❌ <b>Не удалось загрузить файл</b>\n\nПопробуйте ещё раз."


async def _upload_and_get_reply(
    file_id: str, project_id: int, user_id: int, comment: str | None, filename: str,
) -> str:
    """Run the upload and return the message to show the manager."""
    try:
        call_id, reason = await _upload_file(file_id, project_id, user_id, comment, filename)
    except _FileTooLargeError:
        return _TOO_LARGE_MSG
    if call_id:
        return (
            f"✅ <b>Звонок #{call_id} принят в обработку</b>\n\n"
            f"🎙 Транскрибация → 🧠 AI-анализ → 📊 результат в панели.\n"
            f"Проверить статус: /status"
        )
    return reason or _GENERIC_FAIL_MSG


def _extract_file_info(message: Message) -> tuple[str, str] | None:
    """
    Extract (file_id, filename) from a message with an audio/video/voice/document.
    Returns None if the message has no supported attachment.
    """
    if message.audio:
        return message.audio.file_id, message.audio.file_name or "audio.mp3"
    if message.voice:
        return message.voice.file_id, "voice.ogg"
    if message.video:
        return message.video.file_id, message.video.file_name or "video.mp4"
    if message.video_note:
        return message.video_note.file_id, "video_note.mp4"
    if message.document:
        return message.document.file_id, message.document.file_name or "file"
    return None


# ── Handlers ──────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    telegram_id = message.from_user.id if message.from_user else None
    if telegram_id is None:
        return

    projects = await _fetch_manager_projects(telegram_id)
    if projects is None:
        await message.answer(_SERVICE_UNAVAILABLE_MSG)
        return
    if not projects:
        await message.answer(_NOT_IN_PROJECT_MSG)
        return

    names = "\n".join(f"• {_esc(p['name'])}" for p in projects)
    await message.answer(
        "🎙 <b>Call Analytics</b>\n\n"
        "Присылайте мне записи звонков — я передаю их на транскрибацию "
        "и AI-оценку по критериям вашего проекта.\n\n"
        f"<b>Ваши проекты:</b>\n{names}\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📎 Отправьте аудио или видеофайл со звонком\n"
        "📋 /status — статус последних звонков"
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    telegram_id = message.from_user.id if message.from_user else None
    if telegram_id is None:
        return

    from sqlalchemy import select
    from database import User, UserRole, Call, AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id, User.role == UserRole.MANAGER)
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                await message.answer("⚠️ Вы не зарегистрированы в системе.")
                return

            calls_result = await session.execute(
                select(Call)
                .where(Call.user_id == user.id)
                .order_by(Call.created_at.desc())
                .limit(5)
            )
            calls = calls_result.scalars().all()
    except Exception:
        logger.exception("DB error in /status for telegram_id=%d", telegram_id)
        await message.answer(_SERVICE_UNAVAILABLE_MSG)
        return

    if not calls:
        await message.answer("📭 У вас пока нет загруженных звонков.")
        return

    status_emoji = {
        "uploaded": "⏳",
        "converting": "🔄",
        "transcribing": "✍️",
        "analyzing": "🧠",
        "done": "✅",
        "error": "❌",
    }
    status_label = {
        "uploaded": "в очереди",
        "converting": "конвертация",
        "transcribing": "транскрибация",
        "analyzing": "AI-анализ",
        "done": "готово",
        "error": "ошибка",
    }
    lines = []
    for call in calls:
        emoji = status_emoji.get(call.status.value, "❓")
        label = status_label.get(call.status.value, call.status.value)
        date_str = call.created_at.strftime("%d.%m %H:%M")
        name = _esc(call.original_filename or f"звонок #{call.id}")
        lines.append(f"{emoji} <code>{date_str}</code> — {name}\n    <i>{label}</i>")

    await message.answer("📋 <b>Последние 5 звонков</b>\n━━━━━━━━━━━━━━━\n" + "\n".join(lines))


@router.message(Command("skip"), StateFilter(UploadFlow.waiting_comment))
async def cmd_skip_comment(message: Message, state: FSMContext) -> None:
    """Manager sends /skip instead of a comment."""
    data = await state.get_data()
    await state.clear()

    reply = await _upload_and_get_reply(
        file_id=data["file_id"],
        project_id=data["project_id"],
        user_id=data["user_id"],
        comment=None,
        filename=data["filename"],
    )
    await message.answer(reply)


@router.message(
    StateFilter(UploadFlow.waiting_comment),
    F.text,
    ~F.text.startswith("/"),
)
async def receive_comment(message: Message, state: FSMContext) -> None:
    """Manager sent a text comment while in WaitingComment state."""
    data = await state.get_data()
    await state.clear()

    comment = (message.text or "")[:_MAX_COMMENT_LEN]
    reply = await _upload_and_get_reply(
        file_id=data["file_id"],
        project_id=data["project_id"],
        user_id=data["user_id"],
        comment=comment,
        filename=data["filename"],
    )
    await message.answer(reply)


@router.callback_query(F.data == "skip_comment")
async def cb_skip_comment(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer("Сообщение недоступно, отправьте файл заново.", show_alert=True)
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)

    reply = await _upload_and_get_reply(
        file_id=data["file_id"],
        project_id=data["project_id"],
        user_id=data["user_id"],
        comment=None,
        filename=data["filename"],
    )
    await callback.message.answer(reply)
    await callback.answer()


@router.callback_query(F.data == "add_comment")
async def cb_add_comment(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer("Сообщение недоступно, отправьте файл заново.", show_alert=True)
        await state.clear()
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✍️ Напишите комментарий к звонку:")
    await state.set_state(UploadFlow.waiting_comment)
    await callback.answer()


@router.callback_query(F.data.startswith("project:"))
async def cb_select_project(callback: CallbackQuery, state: FSMContext) -> None:
    """Manager selected a project when they belong to multiple."""
    if callback.message is None or callback.data is None:
        await callback.answer("Сообщение недоступно, отправьте файл заново.", show_alert=True)
        await state.clear()
        return
    project_id = int(callback.data.split(":")[1])
    data = await state.get_data()

    # Guard: file_id is lost if the bot restarted between message and callback press
    if not data.get("file_id"):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(_SESSION_EXPIRED_MSG)
        await state.clear()
        await callback.answer()
        return

    await callback.message.edit_reply_markup(reply_markup=None)

    telegram_id = callback.from_user.id
    projects = await _fetch_manager_projects(telegram_id)
    if projects is None:
        await callback.message.answer(_SERVICE_UNAVAILABLE_MSG)
        await state.clear()
        await callback.answer()
        return
    user_id = next((p["user_id"] for p in projects if p["id"] == project_id), None)
    if user_id is None:
        await callback.message.answer("⚠️ Проект не найден.")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(project_id=project_id, user_id=user_id)
    await callback.message.answer(
        "💬 Хотите добавить комментарий к звонку?",
        reply_markup=_comment_keyboard(),
    )
    await callback.answer()


@router.message(
    F.audio | F.voice | F.video | F.video_note | F.document,
    StateFilter(None),  # only when not already in a state
)
async def receive_file(message: Message, state: FSMContext) -> None:
    """
    Manager sent an audio/video file.
    Determine project, then ask for comment.
    """
    telegram_id = message.from_user.id if message.from_user else None
    if telegram_id is None:
        return

    file_info = _extract_file_info(message)
    if file_info is None:
        await message.answer("⚠️ Неподдерживаемый тип файла.")
        return

    file_id, filename = file_info

    projects = await _fetch_manager_projects(telegram_id)
    if projects is None:
        await message.answer(_SERVICE_UNAVAILABLE_MSG)
        return
    if not projects:
        await message.answer(_NOT_IN_PROJECT_MSG)
        return

    if len(projects) == 1:
        project = projects[0]
        await state.update_data(
            file_id=file_id,
            filename=filename,
            project_id=project["id"],
            user_id=project["user_id"],
        )
        await message.answer(
            "📎 <b>Файл получен</b>\n\nХотите добавить комментарий?",
            reply_markup=_comment_keyboard(),
        )
    else:
        # Multiple projects — ask which one
        await state.update_data(file_id=file_id, filename=filename)
        await message.answer(
            "📂 <b>К какому проекту относится этот звонок?</b>",
            reply_markup=_projects_keyboard(projects),
        )
