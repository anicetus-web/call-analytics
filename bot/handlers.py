"""
Telegram bot handlers (aiogram 3.x).

Commands (shown in the per-chat menu button, next to the message input):
  /start           — begin a session: auto-picks the project if the manager
                      has only one, otherwise asks which one. The chosen
                      project stays "active" for every file sent afterwards,
                      so uploads no longer ask "which project?" every time.
  /switch_project  — re-pick the active project (only shown in the menu when
                      the manager belongs to more than one project)
  /finish          — end the session (drops the active project + any
                      in-progress upload); next file falls back to asking
  /status          — the last 10 calls and their statuses
  /skip            — in WaitingComment state: upload the call without a comment

Session state (active_project_id / active_user_id) lives in FSM storage data,
independent of the FSM *state* field, so it survives the state.clear() that
happens after each individual upload completes — see _reset_upload_state().

Flow (once a session is active):
  1. Manager sends an audio/video/voice/document message
  2. Bot shows inline keyboard: "Add comment" | "Skip"
  3. Manager picks "Add comment" → enters WaitingComment state
     OR picks "Skip" → file is uploaded immediately without comment
  4. In WaitingComment state: any text message is treated as the comment

Manager ↔ Project mapping: a manager can belong to multiple projects. If a
file arrives with no active session yet (manager never ran /start), the bot
falls back to the old per-upload behavior: auto-pick if there's only one
project, otherwise ask — and that answer becomes the active session too.

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
    BotCommand, BotCommandScopeChat, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, Message,
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


async def _persist_session(user_id: int, project_id: int | None) -> None:
    """Mirror the FSM session (active_project_id) onto the User row so the admin
    panel can show "session active / no session" per manager — the FSM storage
    itself is process-local memory, invisible outside the bot process.
    project_id=None marks the session as ended (used by /finish)."""
    from datetime import datetime, timezone
    from sqlalchemy import update
    from database import User, AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    session_project_id=project_id,
                    session_started_at=datetime.now(timezone.utc) if project_id is not None else None,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to persist session state for user_id=%d", user_id)


def _projects_keyboard(projects: list[dict[str, Any]], mode: str) -> InlineKeyboardMarkup:
    """mode is "session" (picking the active project via /start or /switch_project)
    or "upload" (picking which project a specific pending file belongs to) —
    encoded in callback_data so cb_select_project knows how to react."""
    buttons = [
        [InlineKeyboardButton(text=p["name"], callback_data=f"project:{mode}:{p['id']}")]
        for p in projects
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _sync_commands(chat_id: int, projects: list[dict[str, Any]]) -> None:
    """Set the per-chat command menu (the button left of the message input).
    /switch_project only appears for managers who actually have >1 project."""
    commands = [BotCommand(command="start", description="Начать сессию")]
    if len(projects) > 1:
        commands.append(BotCommand(command="switch_project", description="Сменить проект"))
    commands.append(BotCommand(command="finish", description="Закончить сессию"))
    commands.append(BotCommand(command="status", description="Последние 10 звонков"))
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception:
        logger.exception("Failed to set per-chat commands for chat_id=%d", chat_id)


async def _reset_upload_state(state: FSMContext) -> None:
    """Clear the per-upload FSM state (file_id/filename/project_id/user_id) after
    a call is uploaded, while preserving the ongoing session's active project —
    plain state.clear() would wipe that too and force a re-pick on every file."""
    data = await state.get_data()
    preserved = {k: v for k, v in data.items() if k in ("active_project_id", "active_user_id")}
    await state.set_state(None)
    await state.set_data(preserved)


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

    # The filename comes from the Telegram sender — strip any path components
    # ("../../x", "..\\x") so a crafted name can't write outside TEMP_DIR.
    safe_filename = os.path.basename(original_filename.replace("\\", "/")) or "file"

    # Write to a temp file instead of buffering in memory — avoids holding 200 MB as bytes.
    tmp_path = os.path.join(settings.TEMP_DIR, f"bot_{uuid.uuid4().hex}_{safe_filename}")
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
                    files={"file": (safe_filename, f)},
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
async def cmd_start(message: Message, state: FSMContext) -> None:
    telegram_id = message.from_user.id if message.from_user else None
    if telegram_id is None:
        return

    # /start may arrive mid-upload (e.g. while waiting_comment) — drop the
    # in-progress upload so the manager doesn't stay stuck in that state.
    await _reset_upload_state(state)

    projects = await _fetch_manager_projects(telegram_id)
    if projects is None:
        await message.answer(_SERVICE_UNAVAILABLE_MSG)
        return
    if not projects:
        await message.answer(_NOT_IN_PROJECT_MSG)
        return

    await _sync_commands(message.chat.id, projects)

    if len(projects) == 1:
        project = projects[0]
        await state.update_data(active_project_id=project["id"], active_user_id=project["user_id"])
        await _persist_session(project["user_id"], project["id"])
        await message.answer(
            "🎙 <b>Call Analytics</b>\n\n"
            f"✅ Сессия начата. Проект: <b>{_esc(project['name'])}</b>\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📎 Отправьте аудио или видеофайл со звонком\n"
            "📋 /status — последние 10 звонков\n"
            "🏁 /finish — закончить сессию"
        )
    else:
        await message.answer(
            "🎙 <b>Call Analytics</b>\n\n"
            "У вас несколько проектов — выберите, с каким работаем сейчас:",
            reply_markup=_projects_keyboard(projects, mode="session"),
        )


@router.message(Command("switch_project"))
async def cmd_switch_project(message: Message) -> None:
    telegram_id = message.from_user.id if message.from_user else None
    if telegram_id is None:
        return

    projects = await _fetch_manager_projects(telegram_id)
    if projects is None:
        await message.answer(_SERVICE_UNAVAILABLE_MSG)
        return
    if len(projects) < 2:
        await message.answer("У вас только один проект — переключаться не на что.")
        return

    await message.answer("📂 Выберите проект:", reply_markup=_projects_keyboard(projects, mode="session"))


@router.message(Command("finish"))
async def cmd_finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    active_user_id = data.get("active_user_id")
    await state.clear()
    if active_user_id is not None:
        await _persist_session(active_user_id, None)
    await bot.set_my_commands(
        [BotCommand(command="start", description="Начать сессию")],
        scope=BotCommandScopeChat(chat_id=message.chat.id),
    )
    await message.answer("🏁 <b>Сессия завершена</b>\n\nОтправьте /start, когда будете готовы продолжить.")


_STATUS_LIMIT = 10


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
                .limit(_STATUS_LIMIT)
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

    await message.answer(
        f"📋 <b>Последние {len(calls)} звонков</b>\n━━━━━━━━━━━━━━━\n" + "\n".join(lines)
    )


@router.message(Command("skip"), StateFilter(UploadFlow.waiting_comment))
async def cmd_skip_comment(message: Message, state: FSMContext) -> None:
    """Manager sends /skip instead of a comment."""
    data = await state.get_data()
    await _reset_upload_state(state)

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
    await _reset_upload_state(state)

    comment = (message.text or "")[:_MAX_COMMENT_LEN]
    reply = await _upload_and_get_reply(
        file_id=data["file_id"],
        project_id=data["project_id"],
        user_id=data["user_id"],
        comment=comment,
        filename=data["filename"],
    )
    await message.answer(reply)


@router.message(
    StateFilter(UploadFlow.waiting_comment),
    F.audio | F.voice | F.video | F.video_note | F.document,
)
async def receive_file_while_waiting_comment(message: Message) -> None:
    """A new file arrived while we're still waiting for the previous file's
    comment. Without this the media wouldn't match any handler (receive_file
    is StateFilter(None)) and would be dropped silently — tell the manager to
    finish the current upload first."""
    await message.answer(
        "⏳ Сначала завершите текущую загрузку: напишите комментарий к "
        "отправленному звонку или нажмите /skip, чтобы пропустить его."
    )


@router.callback_query(F.data == "skip_comment")
async def cb_skip_comment(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer("Сообщение недоступно, отправьте файл заново.", show_alert=True)
        await _reset_upload_state(state)
        return
    data = await state.get_data()
    await _reset_upload_state(state)
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
        await _reset_upload_state(state)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✍️ Напишите комментарий к звонку:")
    await state.set_state(UploadFlow.waiting_comment)
    await callback.answer()


@router.callback_query(F.data.startswith("project:"))
async def cb_select_project(callback: CallbackQuery, state: FSMContext) -> None:
    """Manager picked a project — either to start/switch their session (mode
    "session", from /start or /switch_project) or to answer "which project is
    this file for" (mode "upload", from receive_file when no session was active
    yet). callback_data is "project:<mode>:<id>"."""
    if callback.message is None or callback.data is None:
        await callback.answer("Сообщение недоступно, отправьте файл заново.", show_alert=True)
        await _reset_upload_state(state)
        return

    _, mode, project_id_str = callback.data.split(":")
    project_id = int(project_id_str)

    telegram_id = callback.from_user.id
    projects = await _fetch_manager_projects(telegram_id)
    if projects is None:
        await callback.message.answer(_SERVICE_UNAVAILABLE_MSG)
        await callback.answer()
        return
    project = next((p for p in projects if p["id"] == project_id), None)
    if project is None:
        await callback.message.answer("⚠️ Проект не найден.")
        await callback.answer()
        return

    await callback.message.edit_reply_markup(reply_markup=None)

    if mode == "upload":
        # Guard: file_id is lost if the bot restarted between message and callback press
        data = await state.get_data()
        if not data.get("file_id"):
            await callback.message.answer(_SESSION_EXPIRED_MSG)
            await _reset_upload_state(state)
            await callback.answer()
            return
        await state.update_data(
            project_id=project_id, user_id=project["user_id"],
            active_project_id=project_id, active_user_id=project["user_id"],
        )
        await _persist_session(project["user_id"], project_id)
        await callback.message.answer(
            "💬 Хотите добавить комментарий к звонку?",
            reply_markup=_comment_keyboard(),
        )
    else:  # mode == "session"
        await state.update_data(active_project_id=project_id, active_user_id=project["user_id"])
        await _persist_session(project["user_id"], project_id)
        await callback.message.answer(
            f"✅ <b>Сессия начата</b>\nПроект: {_esc(project['name'])}\n\n"
            "Отправляйте записи звонков — выбирать проект каждый раз больше не нужно."
        )
        await _sync_commands(callback.message.chat.id, projects)

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

    # An active session (started via /start or /switch_project) already knows
    # the project — skip straight to the comment step, no need to ask again.
    session_data = await state.get_data()
    active_project_id = session_data.get("active_project_id")
    active_user_id = session_data.get("active_user_id")
    if active_project_id and active_user_id:
        await state.update_data(
            file_id=file_id, filename=filename,
            project_id=active_project_id, user_id=active_user_id,
        )
        await message.answer(
            "📎 <b>Файл получен</b>\n\nХотите добавить комментарий?",
            reply_markup=_comment_keyboard(),
        )
        return

    projects = await _fetch_manager_projects(telegram_id)
    if projects is None:
        await message.answer(_SERVICE_UNAVAILABLE_MSG)
        return
    if not projects:
        await message.answer(_NOT_IN_PROJECT_MSG)
        return

    if len(projects) == 1:
        # No /start yet, but there's only one possible project — adopt it as
        # the session too, so the next file skips this branch entirely.
        project = projects[0]
        await state.update_data(
            file_id=file_id,
            filename=filename,
            project_id=project["id"],
            user_id=project["user_id"],
            active_project_id=project["id"],
            active_user_id=project["user_id"],
        )
        await _persist_session(project["user_id"], project["id"])
        await message.answer(
            "📎 <b>Файл получен</b>\n\nХотите добавить комментарий?",
            reply_markup=_comment_keyboard(),
        )
    else:
        # Multiple projects and no active session — ask which one this file is for.
        await state.update_data(file_id=file_id, filename=filename)
        await message.answer(
            "📂 <b>К какому проекту относится этот звонок?</b>",
            reply_markup=_projects_keyboard(projects, mode="upload"),
        )
