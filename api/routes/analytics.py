"""
Analytics endpoints for the admin web panel.

Aggregates call analysis results into project-level and manager-level summaries.

Endpoints:
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
"""

from datetime import date, datetime, time, timezone
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


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _assert_project_exists(db: AsyncSession, project_id: int) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")



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
