"""
Calls endpoints.

Two categories of clients use these:
1. Telegram bot — uploads files and creates Call records
2. Admin web panel — lists calls, views detail, listens to recordings

Bot upload flow:
  POST /api/calls/upload
    - Accepts multipart form: file + project_id + user_id + comment(optional)
    - Validates user is a member of the project
    - Uploads raw file to S3
    - Creates Call record in UPLOADED status
    - Enqueues call for processing
    - Returns {call_id}

Admin read flow:
  GET  /api/calls                    — list with filters (project, status, date range)
  GET  /api/calls/{id}               — call detail with transcription + results
  GET  /api/calls/{id}/audio         — pre-signed S3 URL to listen to recording
  POST /api/calls/{id}/reprocess     — reset to UPLOADED and re-enqueue

Bot uses a pre-shared secret header (X-Bot-Secret) instead of JWT for simplicity.
"""

import hmac
import logging
import os
import uuid
from typing import Annotated
from datetime import date, datetime, time, timezone

import httpx

logger = logging.getLogger(__name__)

from fastapi import (
    APIRouter, Depends, File, Form, Header, HTTPException, Query,
    UploadFile, status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin, TokenData
from config import settings
from database import (
    Call, CallStatus, Project, ProjectMember, User, Transcription,
    AnalysisResult, CallGroupAnalysis, get_db,
)
from services import storage
from services import task_queue

async def _enqueue_call(call_id: int) -> bool:
    """
    Enqueue a call for processing.
    - RUN_WORKER=true in this process → direct in-memory enqueue.
    - WORKER_URL set → HTTP POST to the dedicated worker container.
    - Otherwise → call is saved in DB; worker picks it up on next restart
      via _load_pending_calls startup recovery.
    Returns True if enqueued successfully.
    """
    if settings.RUN_WORKER:
        return task_queue.enqueue(call_id)

    if settings.WORKER_URL:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{settings.WORKER_URL.rstrip('/')}/internal/enqueue/{call_id}",
                    headers={"X-Bot-Secret": settings.BOT_SECRET},
                )
                return resp.status_code == 200 and resp.json().get("enqueued", False)
        except Exception:
            logger.warning(
                "Failed to signal worker for call %d — will process on worker restart",
                call_id,
            )
            return False

    logger.info("No WORKER_URL set; call %d queued for next worker restart", call_id)
    return False

router = APIRouter(prefix="/api/calls", tags=["calls"])

_ALLOWED_EXTENSIONS = {".ogg", ".mp3", ".wav", ".mp4", ".m4a", ".oga", ".opus", ".webm"}
_MAX_FILE_SIZE_MB = 200
_MAX_FILE_BYTES = _MAX_FILE_SIZE_MB * 1024 * 1024


# ── Schemas ───────────────────────────────────────────────────────────────────

class CallUploadResponse(BaseModel):
    call_id: int


class AnalysisResultOut(BaseModel):
    metric_item_id: int
    metric_item_name: str
    position: int
    score: float
    timecode_start: float | None

    model_config = {"from_attributes": True}


class TranscriptSegmentOut(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionOut(BaseModel):
    full_text: str
    language: str | None
    segments: list[TranscriptSegmentOut]

    model_config = {"from_attributes": True}


class GroupAnalysisOut(BaseModel):
    metric_group_id: int
    metric_group_name: str
    pains_found: list[str]
    pains_addressed: str
    weak_spots: list[str]
    summary: str


class CallDetailOut(BaseModel):
    id: int
    project_id: int
    user_id: int
    original_filename: str | None
    duration_seconds: int | None
    comment: str | None
    status: CallStatus
    language: str | None
    error_message: str | None
    created_at: datetime
    transcription: TranscriptionOut | None
    analysis_results: list[AnalysisResultOut]
    group_analyses: list[GroupAnalysisOut]

    model_config = {"from_attributes": True}


class CallListItem(BaseModel):
    id: int
    project_id: int
    user_id: int
    original_filename: str | None
    duration_seconds: int | None
    status: CallStatus
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Bot authentication ────────────────────────────────────────────────────────

def _verify_bot_secret(x_bot_secret: str | None = Header(default=None)) -> None:
    # compare_digest needs bytes when non-ASCII is possible — a str comparison
    # would raise TypeError (→ 500) on a crafted header instead of returning 401.
    if x_bot_secret is None or not hmac.compare_digest(
        x_bot_secret.encode("utf-8"), settings.BOT_SECRET.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bot secret",
        )


# ── Upload endpoint (bot) ─────────────────────────────────────────────────────

@router.post("/upload", response_model=CallUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_call(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(_verify_bot_secret)],
    file: UploadFile = File(...),
    project_id: int = Form(...),
    user_id: int = Form(...),
    comment: str | None = Form(default=None),
) -> CallUploadResponse:
    # Validate file extension
    filename = file.filename or "audio"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    # Validate project exists and is active
    proj_result = await db.execute(
        select(Project).where(Project.id == project_id, Project.is_active.is_(True))
    )
    if proj_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active project with id={project_id} not found",
        )

    # Validate user is a member of the project
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if member_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this project",
        )

    # Stream the upload to a temp file in chunks — buffering the whole body in
    # memory would cost up to _MAX_FILE_SIZE_MB of RAM per concurrent request.
    os.makedirs(settings.TEMP_DIR, exist_ok=True)
    tmp_path = os.path.join(settings.TEMP_DIR, f"upload_{uuid.uuid4().hex}{ext}")
    try:
        size = 0
        with open(tmp_path, "wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_FILE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds {_MAX_FILE_SIZE_MB} MB limit",
                    )
                fh.write(chunk)
        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Uploaded file is empty",
            )

        # Create Call record (get ID before S3 upload so key includes call_id)
        call = Call(
            project_id=project_id,
            user_id=user_id,
            original_filename=filename,
            comment=comment,
            status=CallStatus.UPLOADED,
        )
        db.add(call)
        await db.flush()  # populates call.id

        # Upload the ORIGINAL file to S3 under a stable key. This file is never
        # overwritten; the converted audio is later stored under a separate key
        # (audio.ogg).
        original_key = storage.build_key(call.id, f"original{ext}")
        await storage.upload_file(tmp_path, original_key)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # original_file_path points at the source; file_path stays None until conversion.
    call.original_file_path = original_key
    await db.flush()

    # Commit before enqueuing — the worker must see the committed row in DB
    await db.commit()

    # Enqueue for background processing
    if not await _enqueue_call(call.id):
        # Queue full or worker unreachable — call is saved; worker will pick it up on restart
        logger.warning("Call %d saved but not enqueued", call.id)

    return CallUploadResponse(call_id=call.id)


# ── Admin read endpoints ──────────────────────────────────────────────────────

@router.get("", response_model=list[CallListItem])
async def list_calls(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    status_filter: CallStatus | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Call]:
    q = select(Call).order_by(Call.created_at.desc()).limit(limit).offset(offset)

    if project_id is not None:
        q = q.where(Call.project_id == project_id)
    if user_id is not None:
        q = q.where(Call.user_id == user_id)
    if status_filter is not None:
        q = q.where(Call.status == status_filter)
    if date_from is not None:
        q = q.where(Call.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to is not None:
        q = q.where(Call.created_at < datetime.combine(date_to + date.resolution, time.min, tzinfo=timezone.utc))

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{call_id}", response_model=CallDetailOut)
async def get_call(
    call_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> CallDetailOut:
    result = await db.execute(
        select(Call)
        .where(Call.id == call_id)
        .options(
            selectinload(Call.transcription),
            selectinload(Call.analysis_results).selectinload(AnalysisResult.metric_item),
            selectinload(Call.group_analyses).selectinload(CallGroupAnalysis.metric_group),
        )
    )
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    transcription_out = None
    if call.transcription:
        transcription_out = TranscriptionOut(
            full_text=call.transcription.full_text,
            language=call.language,
            segments=[
                TranscriptSegmentOut(**seg) for seg in (call.transcription.segments or [])
            ],
        )

    results_out = []
    for ar in call.analysis_results:
        if ar.metric_item is not None:
            results_out.append(AnalysisResultOut(
                metric_item_id=ar.metric_item_id,
                metric_item_name=ar.metric_item.name,
                position=ar.metric_item.position,
                score=float(ar.score),
                timecode_start=float(ar.timecode_start) if ar.timecode_start is not None else None,
            ))
    results_out.sort(key=lambda x: x.position)

    group_analyses_out = [
        GroupAnalysisOut(
            metric_group_id=ga.metric_group_id,
            metric_group_name=ga.metric_group.name,
            pains_found=ga.pains_found,
            pains_addressed=ga.pains_addressed,
            weak_spots=ga.weak_spots,
            summary=ga.summary,
        )
        for ga in call.group_analyses
    ]

    return CallDetailOut(
        id=call.id,
        project_id=call.project_id,
        user_id=call.user_id,
        original_filename=call.original_filename,
        duration_seconds=call.duration_seconds,
        comment=call.comment,
        status=call.status,
        language=call.language,
        error_message=call.error_message,
        created_at=call.created_at,
        transcription=transcription_out,
        analysis_results=results_out,
        group_analyses=group_analyses_out,
    )


@router.get("/{call_id}/audio")
async def get_audio_url(
    call_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> dict:
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    # Prefer the original recording (real audio quality); fall back to the converted WAV.
    audio_key = call.original_file_path or call.file_path
    if not audio_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not available")

    url = await storage.generate_presigned_url(audio_key, expires_in=3600)
    return {"url": url, "expires_in": 3600}


@router.post("/{call_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_call(
    call_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> dict:
    """
    Reset a failed/stuck call to the earliest pipeline stage whose result is
    missing, and re-enqueue. Useful for retrying after fixing an error or
    refilling OpenAI quota. Completed stages are not repeated: an existing
    transcription skips Whisper, an existing converted file skips FFmpeg.
    """
    result = await db.execute(
        select(Call).where(Call.id == call_id).options(selectinload(Call.transcription))
    )
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    if call.status == CallStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Call is already done. Cannot reprocess.",
        )

    if not call.original_file_path:
        # Defensive: refuse to reprocess a row whose source we cannot locate.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Call has no original_file_path; source recording is unrecoverable.",
        )

    # The advisory lock in process_call protects against double-processing
    # if the call is still queued.
    if call.transcription is not None:
        # Transcription exists → only the LLM stage needs to run. The pipeline's
        # TRANSCRIBING branch detects the existing transcription and skips Whisper.
        call.status = CallStatus.TRANSCRIBING
    elif call.file_path:
        # Converted audio exists → skip FFmpeg, redo Whisper (clear its output).
        call.status = CallStatus.TRANSCRIBING
        call.language = None
    else:
        # Nothing derived yet → full re-run from conversion.
        call.status = CallStatus.UPLOADED
        call.language = None
        call.duration_seconds = None
    call.error_message = None
    await db.flush()
    await db.commit()  # worker must see committed status before dequeuing

    if not await _enqueue_call(call.id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue is full, try again later",
        )

    return {"call_id": call_id, "status": call.status}
