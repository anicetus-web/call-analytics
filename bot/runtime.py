"""
Shared bot + worker startup helpers.

Used by both api/main.py (when an operator runs api+bot+worker in one process for
single-VPS deploys) and bot/worker_main.py (the dedicated worker entrypoint).
Keeping the wiring in one place prevents the two entry points from drifting.
"""

import asyncio
import logging

from config import settings
from services import task_queue

logger = logging.getLogger(__name__)


class BotRuntime:
    """Holds the running bot + worker tasks so callers can shut them down cleanly."""

    def __init__(self) -> None:
        self.telegram_bot = None
        self.bot_task: asyncio.Task | None = None
        self.worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        if settings.RUN_BOT:
            from bot.handlers import dp, bot as telegram_bot
            self.telegram_bot = telegram_bot
            self.bot_task = asyncio.create_task(
                dp.start_polling(telegram_bot),
                name="telegram-bot-polling",
            )
            logger.info("Telegram bot polling started")

        if settings.RUN_WORKER:
            self.worker_task = await task_queue.start(notify_fn=self.notify)
            logger.info("Task queue worker started")

    async def notify(self, telegram_user_id: int, success: bool, message: str) -> None:
        """Send a Telegram message; no-op (with warning) if no bot in this process."""
        if self.telegram_bot is None:
            logger.warning(
                "notify called but no bot runs in this process; message to %d dropped",
                telegram_user_id,
            )
            return
        try:
            await self.telegram_bot.send_message(chat_id=telegram_user_id, text=message)
        except Exception:
            logger.warning("Failed to send Telegram message to user %d", telegram_user_id)

    async def stop(self) -> None:
        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        if self.bot_task and not self.bot_task.done():
            self.bot_task.cancel()
            try:
                await self.bot_task
            except asyncio.CancelledError:
                pass
        if self.telegram_bot is not None:
            try:
                await self.telegram_bot.session.close()
            except Exception:
                pass
