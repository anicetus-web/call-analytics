"""
Call processing pipeline orchestrator.

Pipeline stages per call:
  uploaded → converting → transcribing → analyzing → done | error

Each stage updates calls.status in the DB.
On any unrecoverable error: status = error, error_message is set.
Transcription is saved separately from analysis — if LLM fails,
re-processing does not repeat the Whisper call (transcription already in DB).

Notification callback (notify_fn) is called after processing completes
(success or error) to send Telegram messages to the manager.
"""

import logging
import os
import uuid
from typing import Callable, Awaitable

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import (
    Call, CallStatus, Transcription, AnalysisResult,
    MetricGroup, AsyncSessionLocal,
)
from database.connection import engine
from services.file_converter import convert_for_whisper, ConversionError
from services.transcription import transcribe, TranscriptionError
from services.analyzer import analyze_call, analyze_call_qualitative, QuotaExhaustedError, AnalysisError
from services import storage

logger = logging.getLogger(__name__)

# First key of the two-int Postgres advisory lock. Acts as a namespace so call_id locks
# don't collide with advisory locks used elsewhere. Arbitrary but fixed.
_ADVISORY_LOCK_NAMESPACE = 0x6361  # "ca"

NotifyFn = Callable[[int, bool, str], Awaitable[None]]
# notify_fn(telegram_user_id, success, message)


async def _set_status(
    session: AsyncSession,
    call: Call,
    status: CallStatus,
    error_message: str | None = None,
) -> None:
    call.status = status
    if error_message is not None:
        call.error_message = error_message
    await session.flush()


async def process_call(
    call_id: int,
    notify_fn: NotifyFn | None = None,
) -> None:
    """
    Run the full processing pipeline for a single call.
    Designed to be called from the task queue worker.

    Concurrency: a session-level Postgres advisory lock keyed on call_id serializes
    processing of the same call. The pipeline commits between stages, so a
    transaction-scoped lock would release too early — we hold a session-level lock for
    the whole pipeline and release it in finally.

    The lock is acquired and released on a single dedicated connection checked out
    directly from the engine (NOT the ORM Session used for the pipeline). This is
    deliberate: the pipeline session commits several times mid-run, and each commit
    returns its underlying connection to the pool and may pick up a *different* one
    on the next query — including while other coroutines (the bot handlers share this
    same event loop and connection pool) run concurrently. If the lock were taken via
    that session, unlocking it later could silently run on a different physical
    connection than the one that acquired it (pg_advisory_unlock returns false, not an
    error, when the current connection doesn't hold the lock) — leaking the lock
    forever on whatever connection originally acquired it, permanently stuck as
    "already being processed" for that call_id. Keeping the lock on its own
    never-committed connection for the whole call guarantees lock and unlock always
    hit the same backend session.
    """
    async with engine.connect() as lock_conn:
        lock_acquired = (
            await lock_conn.execute(
                select(func.pg_try_advisory_lock(_ADVISORY_LOCK_NAMESPACE, call_id))
            )
        ).scalar_one()
        if not lock_acquired:
            logger.info("Call %d is already being processed elsewhere, skipping", call_id)
            return

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Call)
                    .where(Call.id == call_id)
                    .options(
                        selectinload(Call.user),
                        selectinload(Call.project),
                        selectinload(Call.transcription),
                    )
                )
                call = result.scalar_one_or_none()

                if call is None:
                    logger.error("process_call: call_id=%d not found", call_id)
                    return

                if call.status == CallStatus.DONE:
                    logger.info("Call %d already done, skipping", call_id)
                    return

                telegram_user_id: int | None = call.user.telegram_id

                try:
                    await _run_pipeline(session, call)
                    await session.commit()

                    logger.info("Call %d processed successfully", call_id)
                    if notify_fn and telegram_user_id:
                        await notify_fn(telegram_user_id, True, _success_summary(call))

                except QuotaExhaustedError:
                    # Do not mark as error — leave in current status so it retries when quota is restored
                    await session.rollback()
                    logger.critical("OpenAI quota exhausted — call %d left in queue", call_id)
                    raise  # propagate to task_queue to pause processing

                except Exception as exc:
                    await session.rollback()
                    async with AsyncSessionLocal() as err_session:
                        err_result = await err_session.execute(select(Call).where(Call.id == call_id))
                        err_call = err_result.scalar_one_or_none()
                        if err_call:
                            await _set_status(
                                err_session, err_call,
                                CallStatus.ERROR,
                                error_message=str(exc)[:1000],
                            )
                            await err_session.commit()

                    logger.exception("Call %d failed: %s", call_id, exc)
                    if notify_fn and telegram_user_id:
                        await notify_fn(
                            telegram_user_id, False,
                            "Не удалось обработать запись. Попробуйте загрузить ещё раз.",
                        )
        finally:
            # Release on the same dedicated connection that acquired it (see docstring).
            try:
                await lock_conn.execute(
                    select(func.pg_advisory_unlock(_ADVISORY_LOCK_NAMESPACE, call_id))
                )
            except Exception:
                logger.warning("Failed to release advisory lock for call %d", call_id)


async def _run_pipeline(session: AsyncSession, call: Call) -> None:
    """
    Execute pipeline stages sequentially, updating status at each step.
    Temp file cleanup is handled internally via try/finally — callers
    do not need to track local paths.
    """
    os.makedirs(settings.TEMP_DIR, exist_ok=True)
    # Unique per-run suffix so concurrent or retried runs never collide on temp paths.
    run_tag = uuid.uuid4().hex
    local_audio: str | None = None

    try:
        # ── Stage 1: Convert ────────────────────────────────────────────────
        # Enter this stage from UPLOADED or CONVERTING (crash recovery).
        # CONVERTING means FFmpeg ran but the commit/S3-upload didn't finish —
        # re-running from scratch is safe because the original file is still in S3.
        if call.status in (CallStatus.UPLOADED, CallStatus.CONVERTING):
            await _set_status(session, call, CallStatus.CONVERTING)
            await session.commit()

            # Always read from the immutable original key; the converted file is written separately.
            original_key = call.original_file_path
            if not original_key:
                raise ConversionError("Call has no original_file_path — cannot process")

            local_original = os.path.join(settings.TEMP_DIR, f"call_{call.id}_{run_tag}_orig")
            await storage.download_file(original_key, local_original)

            local_audio = os.path.join(settings.TEMP_DIR, f"call_{call.id}_{run_tag}.ogg")
            try:
                conv = await convert_for_whisper(local_original, local_audio)
            finally:
                if os.path.exists(local_original):
                    os.remove(local_original)

            # Clamp to SmallInteger max (32767 s ≈ 9.1 h) to avoid DB overflow
            call.duration_seconds = min(conv.duration_seconds, 32767)

            audio_key = storage.build_key(call.id, "audio.ogg")
            await storage.upload_file(local_audio, audio_key)
            call.file_path = audio_key

            await _set_status(session, call, CallStatus.TRANSCRIBING)
            await session.commit()

        # ── Stage 2: Transcribe ──────────────────────────────────────────────
        if call.status == CallStatus.TRANSCRIBING and call.transcription is None:
            if local_audio is None or not os.path.exists(local_audio):
                if not call.file_path:
                    raise TranscriptionError("Call has no converted audio (file_path is empty)")
                # Preserve the key's extension (legacy rows have audio.wav, new ones
                # audio.ogg) — the OpenAI SDK infers the format from the filename.
                ext = os.path.splitext(call.file_path)[1] or ".ogg"
                local_audio = os.path.join(settings.TEMP_DIR, f"call_{call.id}_{run_tag}{ext}")
                await storage.download_file(call.file_path, local_audio)

            result = await transcribe(local_audio)

            if len(result.full_text.strip()) < settings.MIN_TRANSCRIPTION_LENGTH:
                raise TranscriptionError(
                    f"Transcription too short ({len(result.full_text)} chars) — "
                    "check recording quality"
                )

            session.add(Transcription(
                call_id=call.id,
                full_text=result.full_text,
                segments=result.segments,
            ))
            call.language = result.language

            await _set_status(session, call, CallStatus.ANALYZING)
            await session.commit()

            # Converted audio no longer needed locally after successful transcription
            if local_audio and os.path.exists(local_audio):
                os.remove(local_audio)
                local_audio = None

        elif call.status == CallStatus.TRANSCRIBING and call.transcription is not None:
            # Transcription already exists (retry after LLM failure) — skip Whisper
            logger.info("Call %d: transcription already exists, skipping Whisper", call.id)
            await _set_status(session, call, CallStatus.ANALYZING)
            await session.commit()

        # ── Stage 3: Analyze ─────────────────────────────────────────────────
        if call.status == CallStatus.ANALYZING:
            await session.refresh(call, ["transcription"])
            if call.transcription is None:
                raise AnalysisError("Call has no transcription to analyze")

            groups_result = await session.execute(
                select(MetricGroup)
                .where(MetricGroup.project_id == call.project_id)
                .options(selectinload(MetricGroup.items))
            )
            metric_groups = groups_result.scalars().all()

            if not metric_groups:
                logger.info("Call %d: project has no metric groups, marking done", call.id)
            else:
                group_results = await analyze_call(call.transcription.full_text, metric_groups)

                # Collect the metric_item_ids we are about to (re)write — only the active
                # items that were just analyzed. On reprocess we delete ONLY these, so
                # historical results for metrics that have since been deactivated are
                # preserved (consistent with metric soft-delete semantics).
                rewritten_item_ids = {
                    item.metric_item_id
                    for gr in group_results
                    for item in gr.items
                }

                if rewritten_item_ids:
                    existing = await session.execute(
                        select(AnalysisResult).where(
                            AnalysisResult.call_id == call.id,
                            AnalysisResult.metric_item_id.in_(rewritten_item_ids),
                        )
                    )
                    for row in existing.scalars().all():
                        await session.delete(row)
                    # Flush deletes before inserts so DELETE precedes INSERT and the
                    # (call_id, metric_item_id) unique constraint is not violated.
                    await session.flush()

                has_partial_error = False
                for group_result in group_results:
                    if group_result.error:
                        has_partial_error = True
                        logger.warning(
                            "Call %d, group %d: %s",
                            call.id, group_result.metric_group_id, group_result.error,
                        )
                    # Store raw_response once per item (truncated) for traceability
                    raw = group_result.raw_response[:2000] if group_result.raw_response else None
                    for item in group_result.items:
                        session.add(AnalysisResult(
                            call_id=call.id,
                            metric_item_id=item.metric_item_id,
                            score=item.score,
                            timecode_start=item.timecode_start,
                            raw_response=raw,
                        ))

                if has_partial_error:
                    logger.warning("Call %d: some metric groups failed, marked done anyway", call.id)

                # Qualitative read (pains surfaced, how they were handled, weak
                # spots, a short human summary) — separate from per-criterion
                # scores above. Grounded in the SAME criteria shown on the
                # dashboard (not the raw prompt_template, which still has its
                # unsubstituted {items}/{transcription} placeholders). A
                # failure here must not fail the call — the per-criterion
                # scores above are the load-bearing result.
                context_parts = []
                for g in metric_groups:
                    active = [item.name for item in g.items if item.is_active]
                    if active:
                        context_parts.append(f"{g.name}:\n" + "\n".join(f"- {n}" for n in active))
                product_context = "\n\n".join(context_parts)[:6000]
                call.ai_analysis = await analyze_call_qualitative(
                    call.transcription.full_text, product_context,
                )

            await _set_status(session, call, CallStatus.DONE)

    finally:
        # Always clean up local converted audio regardless of success or exception.
        if local_audio and os.path.exists(local_audio):
            os.remove(local_audio)


def _success_summary(call: Call) -> str:
    duration = call.duration_seconds or 0
    minutes, seconds = divmod(duration, 60)
    return (
        f"✅ Звонок обработан!\n"
        f"Длительность: {minutes}:{seconds:02d}\n"
        f"Результаты доступны в личном кабинете."
    )
