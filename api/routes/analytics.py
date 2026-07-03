"""
Analytics endpoints for the admin web panel.

Aggregates call analysis results into project-level and manager-level summaries.

Per-project endpoints (used by ProjectDetailPage):
  GET /api/analytics/projects/{id}/summary
    — per-metric average scores for the project
    — optional date range filter
    — returns: list of {metric_item_id, name, avg_score, call_count}

  GET /api/analytics/projects/{id}/managers
    — per-manager average score across all metric items
    — optional date range filter
    — returns: list of {user_id, name, avg_score, call_count}

  GET /api/analytics/projects/{id}/timeline
    — average score per day for the project (for chart rendering)
    — returns: list of {date, avg_score, call_count}

Global endpoints (used by the "Аналитика" dashboard page), all accept an
optional project_id filter and date range, and aggregate across every project
when project_id is omitted — mirrors the filtering pattern used by /api/calls:
  GET /api/analytics/overview        — top-line stat tiles
  GET /api/analytics/timeline        — calls/day for the line chart
  GET /api/analytics/duration-buckets — call count grouped by duration range
  GET /api/analytics/heatmap         — call count by weekday x hour of day
  GET /api/analytics/managers        — manager leaderboard by avg score

Per-manager endpoints (used by the manager detail page). project_id is
optional — omitted means "across every project this manager belongs to".
  GET /api/analytics/managers/{user_id}/overview  — stat tiles for one manager
  GET /api/analytics/managers/{user_id}/metrics   — per-metric-item avg score
                                                      (requires project_id — metric
                                                      items are defined per project)
  GET /api/analytics/managers/{user_id}/timeline  — calls/day for one manager
  GET /api/analytics/managers/{user_id}/heatmap   — weekday x hour for one manager
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin, TokenData
from database import (
    Project, Call, CallStatus, AnalysisResult, MetricItem, User, get_db,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class MetricSummaryItem(BaseModel):
    metric_item_id: int
    name: str
    position: int
    avg_score: float
    call_count: int


class ManagerSummaryItem(BaseModel):
    user_id: int
    name: str
    avg_score: float
    call_count: int


class TimelineItem(BaseModel):
    date: str  # ISO date string "YYYY-MM-DD"
    avg_score: float
    call_count: int


class OverviewOut(BaseModel):
    total_calls: int
    avg_duration_seconds: float
    avg_score: float
    calls_last_7_days: int


class CallsTimelinePoint(BaseModel):
    date: str  # ISO date string "YYYY-MM-DD"
    call_count: int


class DurationBucket(BaseModel):
    label: str
    call_count: int


class HeatmapCell(BaseModel):
    weekday: int  # 0=Monday .. 6=Sunday (ISO)
    hour: int  # 0..23
    call_count: int


class ManagerOverviewOut(BaseModel):
    total_calls: int
    avg_duration_seconds: float
    avg_score: float
    active_days: int
    last_call_at: str | None  # ISO datetime, null if no calls in range


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _assert_project_exists(db: AsyncSession, project_id: int) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


async def _assert_user_exists(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


def _apply_common_filters(
    q, *,
    project_id: int | None,
    date_from: date | None,
    date_to: date | None,
    user_id: int | None = None,
):
    if project_id is not None:
        q = q.where(Call.project_id == project_id)
    if user_id is not None:
        q = q.where(Call.user_id == user_id)
    if date_from:
        q = q.where(Call.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        q = q.where(Call.created_at < datetime.combine(date_to + date.resolution, time.min, tzinfo=timezone.utc))
    return q



# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/summary", response_model=list[MetricSummaryItem])
async def project_metric_summary(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[MetricSummaryItem]:
    """
    Average score per metric item across all DONE calls in the project.
    Only active metric items are included.
    """
    await _assert_project_exists(db, project_id)

    # Join: AnalysisResult → Call (for project+status+date filter) → MetricItem (for name)
    q = (
        select(
            MetricItem.id,
            MetricItem.name,
            MetricItem.position,
            func.avg(AnalysisResult.score).label("avg_score"),
            func.count(AnalysisResult.id).label("call_count"),
        )
        .join(AnalysisResult, AnalysisResult.metric_item_id == MetricItem.id)
        .join(Call, Call.id == AnalysisResult.call_id)
        .where(
            Call.project_id == project_id,
            Call.status == CallStatus.DONE,
            MetricItem.is_active.is_(True),
        )
        .group_by(MetricItem.id, MetricItem.name, MetricItem.position)
        .order_by(MetricItem.position)
    )

    if date_from:
        q = q.where(Call.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        q = q.where(Call.created_at < datetime.combine(date_to + date.resolution, time.min, tzinfo=timezone.utc))

    rows = (await db.execute(q)).all()
    return [
        MetricSummaryItem(
            metric_item_id=row.id,
            name=row.name,
            position=row.position,
            avg_score=round(float(row.avg_score) if row.avg_score is not None else 0.0, 3),
            call_count=row.call_count,
        )
        for row in rows
    ]


@router.get("/projects/{project_id}/managers", response_model=list[ManagerSummaryItem])
async def project_manager_summary(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[ManagerSummaryItem]:
    """
    Average score per manager across all metric items and DONE calls in the project.
    Managers with zero calls in the period are not included.
    """
    await _assert_project_exists(db, project_id)

    q = (
        select(
            User.id,
            User.name,
            func.avg(AnalysisResult.score).label("avg_score"),
            func.count(func.distinct(Call.id)).label("call_count"),
        )
        .join(Call, Call.user_id == User.id)
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .where(
            Call.project_id == project_id,
            Call.status == CallStatus.DONE,
        )
        .group_by(User.id, User.name)
        .order_by(func.avg(AnalysisResult.score).desc())
    )

    if date_from:
        q = q.where(Call.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        q = q.where(Call.created_at < datetime.combine(date_to + date.resolution, time.min, tzinfo=timezone.utc))

    rows = (await db.execute(q)).all()
    return [
        ManagerSummaryItem(
            user_id=row.id,
            name=row.name,
            avg_score=round(float(row.avg_score) if row.avg_score is not None else 0.0, 3),
            call_count=row.call_count,
        )
        for row in rows
    ]


@router.get("/projects/{project_id}/timeline", response_model=list[TimelineItem])
async def project_timeline(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[TimelineItem]:
    """
    Daily average score for the project (for chart rendering).
    Groups DONE calls by calendar date and averages all metric scores for that day.
    """
    await _assert_project_exists(db, project_id)

    # Truncate to day in UTC. func.date() depends on session TZ and would shift
    # dates for non-UTC servers — date_trunc is explicit and safe.
    day_col = func.date_trunc("day", Call.created_at).label("day")

    q = (
        select(
            day_col,
            func.avg(AnalysisResult.score).label("avg_score"),
            func.count(func.distinct(Call.id)).label("call_count"),
        )
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .where(
            Call.project_id == project_id,
            Call.status == CallStatus.DONE,
        )
        .group_by(day_col)
        .order_by(day_col)
    )

    if date_from:
        q = q.where(Call.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        q = q.where(Call.created_at < datetime.combine(date_to + date.resolution, time.min, tzinfo=timezone.utc))

    rows = (await db.execute(q)).all()
    return [
        TimelineItem(
            # date_trunc returns timestamptz (e.g. 2024-01-15 00:00:00+00:00).
            # Cast to ISO date string with .date() to get "2024-01-15".
            date=row.day.date().isoformat() if hasattr(row.day, 'date') else str(row.day)[:10],
            avg_score=round(float(row.avg_score) if row.avg_score is not None else 0.0, 3),
            call_count=row.call_count,
        )
        for row in rows
    ]


# ── Global dashboard routes ──────────────────────────────────────────────────
# All accept an optional project_id (omitted = across every project), mirroring
# the filter pattern already used by GET /api/calls on the "Звонки" page.

@router.get("/overview", response_model=OverviewOut)
async def overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> OverviewOut:
    calls_q = _apply_common_filters(
        select(
            func.count(Call.id).label("total_calls"),
            func.avg(Call.duration_seconds).label("avg_duration"),
        ),
        project_id=project_id, date_from=date_from, date_to=date_to,
    )
    total_calls, avg_duration = (await db.execute(calls_q)).one()

    score_q = _apply_common_filters(
        select(func.avg(AnalysisResult.score))
        .join(Call, Call.id == AnalysisResult.call_id)
        .where(Call.status == CallStatus.DONE),
        project_id=project_id, date_from=date_from, date_to=date_to,
    )
    avg_score = (await db.execute(score_q)).scalar()

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_q = select(func.count(Call.id)).where(Call.created_at >= week_ago)
    if project_id is not None:
        recent_q = recent_q.where(Call.project_id == project_id)
    calls_last_7_days = (await db.execute(recent_q)).scalar() or 0

    return OverviewOut(
        total_calls=total_calls or 0,
        avg_duration_seconds=round(float(avg_duration), 1) if avg_duration is not None else 0.0,
        avg_score=round(float(avg_score), 3) if avg_score is not None else 0.0,
        calls_last_7_days=calls_last_7_days,
    )


@router.get("/timeline", response_model=list[CallsTimelinePoint])
async def calls_timeline(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[CallsTimelinePoint]:
    """Call volume per calendar day, regardless of processing status."""
    day_col = func.date_trunc("day", Call.created_at).label("day")
    q = _apply_common_filters(
        select(day_col, func.count(Call.id).label("call_count")).group_by(day_col).order_by(day_col),
        project_id=project_id, date_from=date_from, date_to=date_to,
    )
    rows = (await db.execute(q)).all()
    return [
        CallsTimelinePoint(
            date=row.day.date().isoformat() if hasattr(row.day, 'date') else str(row.day)[:10],
            call_count=row.call_count,
        )
        for row in rows
    ]


_DURATION_BUCKETS = [
    ("<1 мин", 0, 60),
    ("1–3 мин", 60, 180),
    ("3–5 мин", 180, 300),
    ("5–10 мин", 300, 600),
    ("10+ мин", 600, None),
]


@router.get("/duration-buckets", response_model=list[DurationBucket])
async def duration_buckets(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[DurationBucket]:
    """Distribution of calls across duration ranges. Calls without a known duration are excluded."""
    base_q = _apply_common_filters(
        select(func.count(Call.id)).where(Call.duration_seconds.isnot(None)),
        project_id=project_id, date_from=date_from, date_to=date_to,
    )

    result: list[DurationBucket] = []
    for label, lo, hi in _DURATION_BUCKETS:
        q = base_q.where(Call.duration_seconds >= lo)
        if hi is not None:
            q = q.where(Call.duration_seconds < hi)
        count = (await db.execute(q)).scalar() or 0
        result.append(DurationBucket(label=label, call_count=count))
    return result


@router.get("/heatmap", response_model=list[HeatmapCell])
async def heatmap(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[HeatmapCell]:
    """Call upload volume by weekday (0=Monday) and hour of day, in UTC."""
    # ISODOW: 1=Monday..7=Sunday — shift to 0=Monday..6=Sunday to match JS Date conventions used on the frontend.
    weekday_col = (func.extract("isodow", Call.created_at) - 1).label("weekday")
    hour_col = func.extract("hour", Call.created_at).label("hour")
    q = _apply_common_filters(
        select(weekday_col, hour_col, func.count(Call.id).label("call_count"))
        .group_by(weekday_col, hour_col),
        project_id=project_id, date_from=date_from, date_to=date_to,
    )
    rows = (await db.execute(q)).all()
    return [
        HeatmapCell(weekday=int(row.weekday), hour=int(row.hour), call_count=row.call_count)
        for row in rows
    ]


@router.get("/managers", response_model=list[ManagerSummaryItem])
async def global_manager_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[ManagerSummaryItem]:
    """Manager leaderboard by average score across DONE calls, optionally scoped to one project."""
    q = _apply_common_filters(
        select(
            User.id,
            User.name,
            func.avg(AnalysisResult.score).label("avg_score"),
            func.count(func.distinct(Call.id)).label("call_count"),
        )
        .join(Call, Call.user_id == User.id)
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .where(Call.status == CallStatus.DONE)
        .group_by(User.id, User.name)
        .order_by(func.avg(AnalysisResult.score).desc()),
        project_id=project_id, date_from=date_from, date_to=date_to,
    )
    rows = (await db.execute(q)).all()
    return [
        ManagerSummaryItem(
            user_id=row.id,
            name=row.name,
            avg_score=round(float(row.avg_score) if row.avg_score is not None else 0.0, 3),
            call_count=row.call_count,
        )
        for row in rows
    ]


# ── Per-manager routes (manager detail page) ─────────────────────────────────
# project_id omitted = across every project the manager has calls in.

@router.get("/managers/{user_id}/overview", response_model=ManagerOverviewOut)
async def manager_overview(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> ManagerOverviewOut:
    await _assert_user_exists(db, user_id)

    day_col = func.date_trunc("day", Call.created_at)
    calls_q = _apply_common_filters(
        select(
            func.count(Call.id).label("total_calls"),
            func.avg(Call.duration_seconds).label("avg_duration"),
            func.max(Call.created_at).label("last_call_at"),
            func.count(func.distinct(day_col)).label("active_days"),
        ),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    total_calls, avg_duration, last_call_at, active_days = (await db.execute(calls_q)).one()

    score_q = _apply_common_filters(
        select(func.avg(AnalysisResult.score))
        .join(Call, Call.id == AnalysisResult.call_id)
        .where(Call.status == CallStatus.DONE),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    avg_score = (await db.execute(score_q)).scalar()

    return ManagerOverviewOut(
        total_calls=total_calls or 0,
        avg_duration_seconds=round(float(avg_duration), 1) if avg_duration is not None else 0.0,
        avg_score=round(float(avg_score), 3) if avg_score is not None else 0.0,
        active_days=active_days or 0,
        last_call_at=last_call_at.isoformat() if last_call_at is not None else None,
    )


@router.get("/managers/{user_id}/metrics", response_model=list[MetricSummaryItem])
async def manager_metrics(
    user_id: int,
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[MetricSummaryItem]:
    """
    Per-metric average score for one manager within one project. project_id is
    required because metric items are defined per project — a score without
    knowing which project's rubric produced it isn't meaningful.
    """
    await _assert_project_exists(db, project_id)
    await _assert_user_exists(db, user_id)

    q = (
        select(
            MetricItem.id,
            MetricItem.name,
            MetricItem.position,
            func.avg(AnalysisResult.score).label("avg_score"),
            func.count(AnalysisResult.id).label("call_count"),
        )
        .join(AnalysisResult, AnalysisResult.metric_item_id == MetricItem.id)
        .join(Call, Call.id == AnalysisResult.call_id)
        .where(
            Call.project_id == project_id,
            Call.user_id == user_id,
            Call.status == CallStatus.DONE,
            MetricItem.is_active.is_(True),
        )
        .group_by(MetricItem.id, MetricItem.name, MetricItem.position)
        .order_by(MetricItem.position)
    )
    if date_from:
        q = q.where(Call.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        q = q.where(Call.created_at < datetime.combine(date_to + date.resolution, time.min, tzinfo=timezone.utc))

    rows = (await db.execute(q)).all()
    return [
        MetricSummaryItem(
            metric_item_id=row.id,
            name=row.name,
            position=row.position,
            avg_score=round(float(row.avg_score) if row.avg_score is not None else 0.0, 3),
            call_count=row.call_count,
        )
        for row in rows
    ]


@router.get("/managers/{user_id}/timeline", response_model=list[CallsTimelinePoint])
async def manager_timeline(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[CallsTimelinePoint]:
    await _assert_user_exists(db, user_id)
    day_col = func.date_trunc("day", Call.created_at).label("day")
    q = _apply_common_filters(
        select(day_col, func.count(Call.id).label("call_count")).group_by(day_col).order_by(day_col),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    rows = (await db.execute(q)).all()
    return [
        CallsTimelinePoint(
            date=row.day.date().isoformat() if hasattr(row.day, 'date') else str(row.day)[:10],
            call_count=row.call_count,
        )
        for row in rows
    ]


@router.get("/managers/{user_id}/heatmap", response_model=list[HeatmapCell])
async def manager_heatmap(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[HeatmapCell]:
    await _assert_user_exists(db, user_id)
    weekday_col = (func.extract("isodow", Call.created_at) - 1).label("weekday")
    hour_col = func.extract("hour", Call.created_at).label("hour")
    q = _apply_common_filters(
        select(weekday_col, hour_col, func.count(Call.id).label("call_count"))
        .group_by(weekday_col, hour_col),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    rows = (await db.execute(q)).all()
    return [
        HeatmapCell(weekday=int(row.weekday), hour=int(row.hour), call_count=row.call_count)
        for row in rows
    ]
