"""
Async task queue for background call processing.

Design:
- Single asyncio.Queue — FIFO, bounded to prevent memory overload
- Single worker coroutine — processes one call at a time (no concurrent LLM calls per project)
- On startup: loads all unfinished calls from DB into the queue (crash recovery)
- On quota exhaustion: pauses processing for QUOTA_PAUSE_SECONDS, then resumes
- Notify callback: injected at startup, used to send Telegram messages

The queue and worker run in the same event loop as FastAPI and aiogram.
Call task_queue.start(notify_fn) once at application startup.
"""

import asyncio
import logging

from sqlalchemy import select

from config import settings
from database import Call, CallStatus, AsyncSessionLocal
from services.analyzer import QuotaExhaustedError
from services.call_processor import process_call, NotifyFn

logger = logging.getLogger(__name__)

# Bounded queue: at most 500 pending tasks to avoid unbounded memory growth
_queue: asyncio.Queue[int] = asyncio.Queue(maxsize=500)
_notify_fn: NotifyFn | None = None

# Statuses that mean "processing was interrupted" — needs to resume on startup
_PENDING_STATUSES = (
    CallStatus.UPLOADED,
    CallStatus.CONVERTING,
    CallStatus.TRANSCRIBING,
    CallStatus.ANALYZING,
)

QUOTA_PAUSE_SECONDS = 60 * 15  # 15 minutes before retrying after quota exhaustion


def enqueue(call_id: int) -> bool:
    """
    Add a call to the processing queue.
    Returns False if the queue is full (should not happen in normal operation).
    Thread-safe (asyncio queue is safe within a single event loop).
    """
    try:
        _queue.put_nowait(call_id)
        logger.debug("Enqueued call %d (queue size: %d)", call_id, _queue.qsize())
        return True
    except asyncio.QueueFull:
        logger.error("Task queue is full! Call %d not enqueued", call_id)
        return False


async def _worker() -> None:
    """
    Main worker loop. Runs forever; picks one call at a time.
    On QuotaExhaustedError: pauses for QUOTA_PAUSE_SECONDS and notifies admins.
    """
    logger.info("Task queue worker started")

    while True:
        call_id = await _queue.get()
        logger.info("Processing call %d (queue remaining: %d)", call_id, _queue.qsize())

        try:
            await process_call(call_id, notify_fn=_notify_fn)
        except QuotaExhaustedError:
            logger.critical(
                "OpenAI quota exhausted. Pausing queue for %d seconds.",
                QUOTA_PAUSE_SECONDS,
            )
            await _notify_admins_quota_exhausted()
            # Sleep FIRST, then re-enqueue — this way all other queued calls
            # also wait out the pause instead of each hitting quota individually
            # and triggering O(N × pause) cascading delays.
            await asyncio.sleep(QUOTA_PAUSE_SECONDS)
            try:
                _queue.put_nowait(call_id)
            except asyncio.QueueFull:
                logger.error("Cannot re-enqueue call %d after quota pause — queue full", call_id)
        except Exception:
            # process_call handles its own exceptions and marks call as error.
            # This catch is a safety net to keep the worker alive.
            logger.exception("Unexpected error in worker for call %d", call_id)
        finally:
            _queue.task_done()


async def _notify_admins_quota_exhausted() -> None:
    """Send quota alert to all admin Telegram IDs configured in settings.

    Only works when the bot runs in the same process as the worker (notify_fn
    is callable). The default docker-compose deploys bot+worker together for
    exactly this reason. If the bot is ever split off, replace this with a
    DB-backed notification table polled by the bot process — but as of today,
    a worker process without a bot will only log the alert, never send it.
    """
    if not _notify_fn or not settings.ADMIN_TELEGRAM_IDS:
        return
    for admin_id in settings.ADMIN_TELEGRAM_IDS:
        try:
            await _notify_fn(
                admin_id,
                False,
                "⚠️ Закончился баланс OpenAI. Обработка звонков приостановлена. "
                f"Возобновление через {QUOTA_PAUSE_SECONDS // 60} мин после пополнения.",
            )
        except Exception:
            logger.warning("Failed to notify admin %d about quota exhaustion", admin_id)


async def _load_pending_calls() -> int:
    """
    On startup: find all calls in non-terminal statuses and enqueue them.
    Returns the count of calls loaded.
    This is the crash-recovery mechanism — no calls are ever permanently lost.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Call.id)
            .where(
                Call.status.in_(_PENDING_STATUSES),
                Call.original_file_path.is_not(None),  # skip legacy rows without source file
            )
            .order_by(Call.created_at.asc())  # FIFO: oldest first
        )
        call_ids = result.scalars().all()

    loaded = 0
    for call_id in call_ids:
        if enqueue(call_id):
            loaded += 1
        else:
            logger.error("Queue full during startup recovery — call %d skipped", call_id)

    if loaded:
        logger.info("Recovered %d pending calls into queue on startup", loaded)
    return loaded


async def start(notify_fn: NotifyFn | None = None) -> asyncio.Task:
    """
    Initialize the task queue and start the background worker.
    Call this once at application startup (e.g. in FastAPI lifespan).

    Returns the worker Task so the caller can cancel it on shutdown.
    """
    global _notify_fn
    _notify_fn = notify_fn

    await _load_pending_calls()

    task = asyncio.create_task(_worker(), name="call-queue-worker")
    logger.info("Task queue started")
    return task
