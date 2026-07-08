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

import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin, TokenData
from database import (
    Project, Call, CallStatus, AnalysisResult, MetricItem, MetricGroup, CallGroupAnalysis,
    User, Transcription, get_db,
)

# Common Russian stopwords + filler words, excluded from the keyword-frequency endpoint.
_STOPWORDS: frozenset[str] = frozenset({
    "и", "в", "не", "на", "я", "что", "он", "с", "как", "а", "то", "все", "она", "так", "его",
    "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "её", "мне", "было",
    "вот", "от", "меня", "ещё", "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну",
    "вдруг", "ли", "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь",
    "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей", "может", "они",
    "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем", "была", "сам",
    "чтобы", "без", "будто", "чего", "раз", "тоже", "себе", "под", "будет", "тогда", "кто",
    "этот", "того", "потому", "этого", "какой", "совсем", "ним", "здесь", "этом", "один",
    "почти", "мой", "тем", "нее", "сейчас", "были", "куда", "зачем", "всех", "никогда",
    "можно", "при", "наконец", "два", "об", "другой", "хоть", "после", "над", "больше",
    "тот", "через", "эти", "нас", "про", "всего", "них", "какая", "много", "разве", "три",
    "эту", "моя", "впрочем", "хорошо", "свою", "этой", "перед", "иногда", "лучше", "чуть",
    "том", "нельзя", "такой", "им", "более", "всегда", "конечно", "всю", "между", "здравствуйте",
    "алло", "спасибо", "пожалуйста",
})

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class MetricSummaryItem(BaseModel):
    metric_item_id: int
    name: str
    position: int
    avg_score: float
    call_count: int
    # Which metric group this criterion belongs to — lets the dashboard render
    # a separate analytics section per group (sales-call checklist, forbidden
    # words, etc.) instead of flattening every group into one mixed list.
    metric_group_id: int
    metric_group_name: str
    metric_group_type: str


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


class TopErrorItem(BaseModel):
    metric_item_id: int
    metric_name: str
    project_id: int
    project_name: str
    fail_count: int
    total_count: int
    fail_rate: float


class QualityDistributionOut(BaseModel):
    high: int   # per-call avg score >= 0.8
    medium: int  # 0.5 <= avg score < 0.8
    low: int    # avg score < 0.5
    total: int


class ManagerTrendItem(BaseModel):
    user_id: int
    name: str
    avg_score: float
    call_count: int
    prev_avg_score: float | None
    delta: float | None  # avg_score - prev_avg_score; null if no calls in the prior period


class KpiOut(BaseModel):
    avg_score: float
    avg_score_delta: float | None  # this week's avg_score minus last week's; null if no prior data
    calls_analyzed: int
    best_manager: ManagerTrendItem | None
    main_problem: TopErrorItem | None


class KeywordItem(BaseModel):
    word: str
    count: int


class TopErrorCallItem(BaseModel):
    call_id: int
    user_id: int
    manager_name: str
    created_at: str  # ISO datetime
    duration_seconds: int | None
    score: float


class ErrorManagerItem(BaseModel):
    user_id: int
    name: str
    fail_count: int


class ManagerErrorSummaryOut(BaseModel):
    user_id: int
    name: str
    call_count: int
    total_errors: int
    top_errors: list[TopErrorItem]


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

    # Join: AnalysisResult → Call (project+status+date filter) → MetricItem (name)
    #       → MetricGroup (so results can be split per group on the dashboard).
    q = (
        select(
            MetricItem.id,
            MetricItem.name,
            MetricItem.position,
            func.avg(AnalysisResult.score).label("avg_score"),
            func.count(AnalysisResult.id).label("call_count"),
            MetricGroup.id.label("group_id"),
            MetricGroup.name.label("group_name"),
            MetricGroup.group_type.label("group_type"),
        )
        .join(AnalysisResult, AnalysisResult.metric_item_id == MetricItem.id)
        .join(Call, Call.id == AnalysisResult.call_id)
        .join(MetricGroup, MetricGroup.id == MetricItem.metric_group_id)
        .where(
            Call.project_id == project_id,
            Call.status == CallStatus.DONE,
            MetricItem.is_active.is_(True),
        )
        .group_by(MetricItem.id, MetricItem.name, MetricItem.position,
                  MetricGroup.id, MetricGroup.name, MetricGroup.group_type)
        # position is unique only within a group, so order by group first to
        # keep each group's items contiguous and correctly sequenced.
        .order_by(MetricGroup.id, MetricItem.position)
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
            metric_group_id=row.group_id,
            metric_group_name=row.group_name,
            metric_group_type=row.group_type.value if hasattr(row.group_type, "value") else str(row.group_type),
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
    """Distribution of calls across duration ranges. Calls without a known duration are excluded.

    All buckets are counted in one query via conditional aggregates
    (COUNT(*) FILTER (WHERE ...)) instead of one round-trip per bucket."""
    bucket_cols = []
    for i, (_, lo, hi) in enumerate(_DURATION_BUCKETS):
        cond = Call.duration_seconds >= lo
        if hi is not None:
            cond = and_(cond, Call.duration_seconds < hi)
        bucket_cols.append(func.count().filter(cond).label(f"b{i}"))

    q = _apply_common_filters(
        select(*bucket_cols).where(Call.duration_seconds.isnot(None)),
        project_id=project_id, date_from=date_from, date_to=date_to,
    )
    row = (await db.execute(q)).one()
    return [
        DurationBucket(label=label, call_count=getattr(row, f"b{i}") or 0)
        for i, (label, _, _) in enumerate(_DURATION_BUCKETS)
    ]


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
            MetricGroup.id.label("group_id"),
            MetricGroup.name.label("group_name"),
            MetricGroup.group_type.label("group_type"),
        )
        .join(AnalysisResult, AnalysisResult.metric_item_id == MetricItem.id)
        .join(Call, Call.id == AnalysisResult.call_id)
        .join(MetricGroup, MetricGroup.id == MetricItem.metric_group_id)
        .where(
            Call.project_id == project_id,
            Call.user_id == user_id,
            Call.status == CallStatus.DONE,
            MetricItem.is_active.is_(True),
        )
        .group_by(MetricItem.id, MetricItem.name, MetricItem.position,
                  MetricGroup.id, MetricGroup.name, MetricGroup.group_type)
        .order_by(MetricGroup.id, MetricItem.position)
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
            metric_group_id=row.group_id,
            metric_group_name=row.group_name,
            metric_group_type=row.group_type.value if hasattr(row.group_type, "value") else str(row.group_type),
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


@router.get("/managers/{user_id}/score-timeline", response_model=list[TimelineItem])
async def manager_score_timeline(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[TimelineItem]:
    """Daily average AI score for one manager (mirrors /projects/{id}/timeline
    but scoped to a manager instead of a whole project). A separate endpoint
    from /managers/{id}/timeline on purpose — that one intentionally counts
    every call regardless of status for the manager's own activity view;
    this one only counts DONE calls, since a score average needs analysis
    results to exist."""
    await _assert_user_exists(db, user_id)
    day_col = func.date_trunc("day", Call.created_at).label("day")
    q = _apply_common_filters(
        select(
            day_col,
            func.avg(AnalysisResult.score).label("avg_score"),
            func.count(func.distinct(Call.id)).label("call_count"),
        )
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .where(Call.status == CallStatus.DONE)
        .group_by(day_col)
        .order_by(day_col),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    rows = (await db.execute(q)).all()
    return [
        TimelineItem(
            date=row.day.date().isoformat() if hasattr(row.day, 'date') else str(row.day)[:10],
            avg_score=round(float(row.avg_score) if row.avg_score is not None else 0.0, 3),
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


# ── Manager-quality dashboard (top errors, quality mix, trend, keywords, KPI) ─
# These back the redesigned "Аналитика" page, which is oriented around
# evaluating manager/call quality rather than raw call volume.

async def _fetch_top_errors(
    db: AsyncSession, *,
    project_id: int | None, date_from: date | None, date_to: date | None, limit: int,
    user_id: int | None = None,
) -> list[TopErrorItem]:
    """Metric items most often scored below 1.0 ("failed"), across all projects
    unless project_id is given. Each row carries its project name because metric
    item names are only unique within a project, not globally."""
    fail_count_expr = func.count(AnalysisResult.id).filter(AnalysisResult.score < 1.0)
    total_count_expr = func.count(AnalysisResult.id)

    q = _apply_common_filters(
        select(
            MetricItem.id,
            MetricItem.name,
            Project.id.label("project_id"),
            Project.name.label("project_name"),
            fail_count_expr.label("fail_count"),
            total_count_expr.label("total_count"),
        )
        .join(AnalysisResult, AnalysisResult.metric_item_id == MetricItem.id)
        .join(Call, Call.id == AnalysisResult.call_id)
        .join(Project, Project.id == Call.project_id)
        .where(Call.status == CallStatus.DONE, MetricItem.is_active.is_(True))
        .group_by(MetricItem.id, MetricItem.name, Project.id, Project.name)
        .having(fail_count_expr > 0)
        .order_by(fail_count_expr.desc())
        .limit(limit),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    rows = (await db.execute(q)).all()
    return [
        TopErrorItem(
            metric_item_id=r.id,
            metric_name=r.name,
            project_id=r.project_id,
            project_name=r.project_name,
            fail_count=r.fail_count,
            total_count=r.total_count,
            fail_rate=round(r.fail_count / r.total_count, 3) if r.total_count else 0.0,
        )
        for r in rows
    ]


async def _fetch_managers_trend(
    db: AsyncSession, *, project_id: int | None,
) -> list[ManagerTrendItem]:
    """Manager leaderboard for the last 7 days, with each manager's avg score
    from the previous 7 days for comparison. Fixed weekly window regardless of
    the page's date filter — this answers "who's improving right now", not an
    arbitrary custom range."""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)

    def _scope(q):
        if project_id is not None:
            q = q.where(Call.project_id == project_id)
        return q

    current_q = _scope(
        select(
            User.id,
            User.name,
            func.avg(AnalysisResult.score).label("avg_score"),
            func.count(func.distinct(Call.id)).label("call_count"),
        )
        .join(Call, Call.user_id == User.id)
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .where(Call.status == CallStatus.DONE, Call.created_at >= week_start)
        .group_by(User.id, User.name)
    )
    prev_q = _scope(
        select(User.id, func.avg(AnalysisResult.score).label("avg_score"))
        .join(Call, Call.user_id == User.id)
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .where(
            Call.status == CallStatus.DONE,
            Call.created_at >= prev_week_start,
            Call.created_at < week_start,
        )
        .group_by(User.id)
    )
    current_rows = (await db.execute(current_q)).all()
    prev_map = {r.id: float(r.avg_score) for r in (await db.execute(prev_q)).all() if r.avg_score is not None}

    result = []
    for r in current_rows:
        avg = float(r.avg_score) if r.avg_score is not None else 0.0
        prev = prev_map.get(r.id)
        result.append(ManagerTrendItem(
            user_id=r.id,
            name=r.name,
            avg_score=round(avg, 3),
            call_count=r.call_count,
            prev_avg_score=round(prev, 3) if prev is not None else None,
            delta=round(avg - prev, 3) if prev is not None else None,
        ))
    result.sort(key=lambda m: m.avg_score, reverse=True)
    return result


@router.get("/top-errors", response_model=list[TopErrorItem])
async def top_errors(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=100),
) -> list[TopErrorItem]:
    return await _fetch_top_errors(
        db, project_id=project_id, user_id=user_id, date_from=date_from, date_to=date_to, limit=limit,
    )


@router.get("/top-errors/{metric_item_id}/calls", response_model=list[TopErrorCallItem])
async def top_error_calls(
    metric_item_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[TopErrorCallItem]:
    """Which specific calls failed a given metric item (score < 1.0), newest
    first — lets the admin drill from "Частые ошибки" straight to the calls
    responsible for that count instead of only seeing an aggregate."""
    result = await db.execute(select(MetricItem).where(MetricItem.id == metric_item_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric item not found")

    q = _apply_common_filters(
        select(
            Call.id.label("call_id"),
            Call.user_id,
            User.name.label("manager_name"),
            Call.created_at,
            Call.duration_seconds,
            AnalysisResult.score,
        )
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .join(User, User.id == Call.user_id)
        .where(
            AnalysisResult.metric_item_id == metric_item_id,
            AnalysisResult.score < 1.0,
            Call.status == CallStatus.DONE,
        )
        .order_by(Call.created_at.desc())
        .limit(limit),
        project_id=None, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    rows = (await db.execute(q)).all()
    return [
        TopErrorCallItem(
            call_id=r.call_id,
            user_id=r.user_id,
            manager_name=r.manager_name,
            created_at=r.created_at.isoformat(),
            duration_seconds=r.duration_seconds,
            score=float(r.score),
        )
        for r in rows
    ]


@router.get("/top-errors/{metric_item_id}/managers", response_model=list[ErrorManagerItem])
async def top_error_managers(
    metric_item_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> list[ErrorManagerItem]:
    """Every manager who ever failed this metric item (score < 1.0), ranked by
    how many times, most first. Returns the full list (not just a top-N) —
    the "Ошибки" section's manager search/drilldown filters this client-side,
    which is cheap even at a few hundred managers."""
    result = await db.execute(select(MetricItem).where(MetricItem.id == metric_item_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric item not found")

    fail_count_expr = func.count(AnalysisResult.id)
    q = _apply_common_filters(
        select(User.id, User.name, fail_count_expr.label("fail_count"))
        .join(Call, Call.user_id == User.id)
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .where(
            AnalysisResult.metric_item_id == metric_item_id,
            AnalysisResult.score < 1.0,
            Call.status == CallStatus.DONE,
        )
        .group_by(User.id, User.name)
        .order_by(fail_count_expr.desc()),
        project_id=project_id, date_from=date_from, date_to=date_to,
    )
    rows = (await db.execute(q)).all()
    return [ErrorManagerItem(user_id=r.id, name=r.name, fail_count=r.fail_count) for r in rows]


@router.get("/managers/{user_id}/error-summary", response_model=ManagerErrorSummaryOut)
async def manager_error_summary(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=100),
) -> ManagerErrorSummaryOut:
    """Card data for the "Ошибки менеджеров" tab: how many calls this manager
    had, how many total scoring failures across all of them, and their most
    frequent failures (top-N, N controlled by the frontend's "show all")."""
    await _assert_user_exists(db, user_id)
    user_row = (await db.execute(select(User.name).where(User.id == user_id))).scalar_one()

    calls_q = _apply_common_filters(
        select(func.count(func.distinct(Call.id)))
        .where(Call.status == CallStatus.DONE),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    call_count = (await db.execute(calls_q)).scalar() or 0

    errors_q = _apply_common_filters(
        select(func.count(AnalysisResult.id))
        .join(Call, Call.id == AnalysisResult.call_id)
        .where(Call.status == CallStatus.DONE, AnalysisResult.score < 1.0),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    total_errors = (await db.execute(errors_q)).scalar() or 0

    top_errors = await _fetch_top_errors(
        db, project_id=project_id, date_from=date_from, date_to=date_to, limit=limit, user_id=user_id,
    )

    return ManagerErrorSummaryOut(
        user_id=user_id, name=user_row, call_count=call_count,
        total_errors=total_errors, top_errors=top_errors,
    )


@router.get("/quality-distribution", response_model=QualityDistributionOut)
async def quality_distribution(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> QualityDistributionOut:
    """Buckets DONE calls by their own average score (across all their metric
    items) into high (>=0.8) / medium (0.5-0.8) / low (<0.5)."""
    call_avg_subq = _apply_common_filters(
        select(Call.id.label("call_id"), func.avg(AnalysisResult.score).label("call_avg"))
        .join(AnalysisResult, AnalysisResult.call_id == Call.id)
        .where(Call.status == CallStatus.DONE)
        .group_by(Call.id),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    ).subquery()

    q = select(
        func.count().filter(call_avg_subq.c.call_avg >= 0.8).label("high"),
        func.count().filter(call_avg_subq.c.call_avg >= 0.5, call_avg_subq.c.call_avg < 0.8).label("medium"),
        func.count().filter(call_avg_subq.c.call_avg < 0.5).label("low"),
    ).select_from(call_avg_subq)

    row = (await db.execute(q)).one()
    return QualityDistributionOut(
        high=row.high, medium=row.medium, low=row.low, total=row.high + row.medium + row.low,
    )


@router.get("/managers/trend", response_model=list[ManagerTrendItem])
async def managers_trend(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
) -> list[ManagerTrendItem]:
    return await _fetch_managers_trend(db, project_id=project_id)


@router.get("/kpi", response_model=KpiOut)
async def kpi(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
) -> KpiOut:
    """Top-of-page KPI row: this week's avg score (+ delta vs last week), how
    many calls have been scored, the top manager this week, and the most
    common scoring failure. All fixed to the last-7-days window, same as
    /managers/trend, so the numbers on the page agree with each other."""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)

    def _scope(q):
        if project_id is not None:
            q = q.where(Call.project_id == project_id)
        if user_id is not None:
            q = q.where(Call.user_id == user_id)
        return q

    current_q = _scope(
        select(func.avg(AnalysisResult.score), func.count(func.distinct(Call.id)))
        .join(Call, Call.id == AnalysisResult.call_id)
        .where(Call.status == CallStatus.DONE, Call.created_at >= week_start)
    )
    prev_q = _scope(
        select(func.avg(AnalysisResult.score))
        .join(Call, Call.id == AnalysisResult.call_id)
        .where(
            Call.status == CallStatus.DONE,
            Call.created_at >= prev_week_start,
            Call.created_at < week_start,
        )
    )
    current_avg, calls_analyzed = (await db.execute(current_q)).one()
    prev_avg = (await db.execute(prev_q)).scalar()

    # best_manager is meaningless (and redundant with the manager filter itself)
    # once a specific manager is already selected — the frontend hides that tile
    # in that case, so skip the extra query.
    trend = [] if user_id is not None else await _fetch_managers_trend(db, project_id=project_id)
    top_errors_list = await _fetch_top_errors(
        db, project_id=project_id, user_id=user_id, date_from=week_start.date(), date_to=None, limit=1,
    )

    avg_score = float(current_avg) if current_avg is not None else 0.0
    return KpiOut(
        avg_score=round(avg_score, 3),
        avg_score_delta=round(avg_score - float(prev_avg), 3) if prev_avg is not None else None,
        calls_analyzed=calls_analyzed or 0,
        best_manager=trend[0] if trend else None,
        main_problem=top_errors_list[0] if top_errors_list else None,
    )


@router.get("/keywords", response_model=list[KeywordItem])
async def keywords(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=15, ge=1, le=50),
) -> list[KeywordItem]:
    """Most frequent words across recent transcripts in scope, excluding common
    Russian stopwords. Capped to the 300 most recent matching calls to keep
    the request cheap — this is a rough word-frequency signal, not exhaustive
    text analytics."""
    q = _apply_common_filters(
        select(Transcription.full_text)
        .join(Call, Call.id == Transcription.call_id)
        .where(Call.status == CallStatus.DONE)
        .order_by(Call.created_at.desc())
        .limit(300),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    rows = (await db.execute(q)).all()

    counter: Counter[str] = Counter()
    for (text,) in rows:
        for word in re.findall(r"[а-яё]{4,}", text.lower()):
            if word not in _STOPWORDS:
                counter[word] += 1

    return [KeywordItem(word=w, count=c) for w, c in counter.most_common(limit)]


# ── Qualitative analysis (pains / weak spots / summary), per metric group ────
# One call can carry several of these — one per metric group (sales checklist,
# forbidden words, script sequence, ...) — instead of one blended-together read.

class QualitativeCallSummary(BaseModel):
    call_id: int
    project_id: int
    manager_id: int
    manager_name: str
    metric_group_id: int
    metric_group_name: str
    created_at: str
    pains_found: list[str]
    pains_addressed: str
    weak_spots: list[str]
    summary: str


async def _fetch_qualitative(
    db: AsyncSession, *,
    user_id: int | None, project_id: int | None,
    date_from: date | None, date_to: date | None, limit: int,
) -> list[QualitativeCallSummary]:
    q = _apply_common_filters(
        select(
            Call.id, Call.project_id, Call.user_id, User.name.label("manager_name"),
            Call.created_at,
            CallGroupAnalysis.metric_group_id, MetricGroup.name.label("group_name"),
            CallGroupAnalysis.pains_found, CallGroupAnalysis.pains_addressed,
            CallGroupAnalysis.weak_spots, CallGroupAnalysis.summary,
        )
        .join(CallGroupAnalysis, CallGroupAnalysis.call_id == Call.id)
        .join(MetricGroup, MetricGroup.id == CallGroupAnalysis.metric_group_id)
        .join(User, User.id == Call.user_id)
        .order_by(Call.created_at.desc())
        .limit(limit),
        project_id=project_id, date_from=date_from, date_to=date_to, user_id=user_id,
    )
    rows = (await db.execute(q)).all()
    return [
        QualitativeCallSummary(
            call_id=r.id,
            project_id=r.project_id,
            manager_id=r.user_id,
            manager_name=r.manager_name,
            metric_group_id=r.metric_group_id,
            metric_group_name=r.group_name,
            created_at=r.created_at.isoformat(),
            pains_found=r.pains_found or [],
            pains_addressed=r.pains_addressed or "",
            weak_spots=r.weak_spots or [],
            summary=r.summary or "",
        )
        for r in rows
    ]


@router.get("/managers/{user_id}/qualitative", response_model=list[QualitativeCallSummary])
async def manager_qualitative(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    project_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[QualitativeCallSummary]:
    """AI's qualitative read (pains surfaced, how addressed, weak spots to
    strengthen, short human summary), one row per (call, metric group), for
    this manager's calls in the period — backs the period filter on the
    manager page."""
    await _assert_user_exists(db, user_id)
    return await _fetch_qualitative(
        db, user_id=user_id, project_id=project_id, date_from=date_from, date_to=date_to, limit=limit,
    )


@router.get("/projects/{project_id}/qualitative", response_model=list[QualitativeCallSummary])
async def project_qualitative(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[QualitativeCallSummary]:
    """Same qualitative feed, scoped to a project instead of a manager — shows
    every manager's calls in that project (each row carries manager_name)."""
    await _assert_project_exists(db, project_id)
    return await _fetch_qualitative(
        db, user_id=user_id, project_id=project_id, date_from=date_from, date_to=date_to, limit=limit,
    )
