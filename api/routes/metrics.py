"""
Metric groups and items CRUD (admin-only).

MetricGroups belong to a Project. Each group has a prompt_template and a list
of MetricItems with positions (1-based, unique per group).

MetricItems use soft delete (is_active=False) to preserve historical
AnalysisResult rows that reference them.

Endpoints:
  GET    /api/projects/{pid}/metric-groups          — list groups for project
  POST   /api/projects/{pid}/metric-groups          — create group
  GET    /api/metric-groups/{id}                    — get group with items
  PATCH  /api/metric-groups/{id}                    — update group
  DELETE /api/metric-groups/{id}                    — hard delete (cascades items if no results)

  GET    /api/metric-groups/{gid}/items             — list items
  POST   /api/metric-groups/{gid}/items             — add item
  PATCH  /api/metric-items/{id}                     — update item name/description
  DELETE /api/metric-items/{id}                     — soft delete (is_active=False)
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin, TokenData
from database import Project, MetricGroup, MetricGroupType, MetricItem, AnalysisResult, get_db

router = APIRouter(tags=["metrics"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class MetricItemOut(BaseModel):
    id: int
    position: int
    name: str
    description: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class MetricGroupOut(BaseModel):
    id: int
    project_id: int
    name: str
    group_type: MetricGroupType
    prompt_template: str
    items: list[MetricItemOut] = []

    model_config = {"from_attributes": True}


class MetricGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    group_type: MetricGroupType
    prompt_template: str = Field(min_length=1)


class MetricGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    prompt_template: str | None = Field(default=None, min_length=1)


class MetricItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None


class MetricItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None)
    clear_description: bool = False  # set true to explicitly clear description to null


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_group_or_404(db: AsyncSession, group_id: int) -> MetricGroup:
    result = await db.execute(
        select(MetricGroup)
        .where(MetricGroup.id == group_id)
        .options(selectinload(MetricGroup.items))
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric group not found")
    return group


async def _get_item_or_404(db: AsyncSession, item_id: int) -> MetricItem:
    result = await db.execute(select(MetricItem).where(MetricItem.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric item not found")
    return item


async def _next_position(db: AsyncSession, group_id: int) -> int:
    """Return max(position) + 1 for the group, or 1 if empty.
    Locks the MetricGroup row to serialize concurrent add_item calls."""
    from sqlalchemy import text
    await db.execute(
        text("SELECT 1 FROM metric_groups WHERE id = :id FOR UPDATE"),
        {"id": group_id},
    )
    result = await db.execute(
        select(func.max(MetricItem.position)).where(MetricItem.metric_group_id == group_id)
    )
    max_pos = result.scalar_one_or_none()
    return (max_pos or 0) + 1


def _group_to_out(group: MetricGroup) -> MetricGroupOut:
    items = sorted(
        [MetricItemOut.model_validate(i) for i in group.items],
        key=lambda x: x.position,
    )
    return MetricGroupOut(
        id=group.id,
        project_id=group.project_id,
        name=group.name,
        group_type=group.group_type,
        prompt_template=group.prompt_template,
        items=items,
    )


# ── Group routes ──────────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/metric-groups", response_model=list[MetricGroupOut])
async def list_groups(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> list[MetricGroupOut]:
    # Verify project exists
    proj = await db.execute(select(Project).where(Project.id == project_id))
    if proj.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    result = await db.execute(
        select(MetricGroup)
        .where(MetricGroup.project_id == project_id)
        .options(selectinload(MetricGroup.items))
        .order_by(MetricGroup.name)
    )
    return [_group_to_out(g) for g in result.scalars().all()]


@router.post(
    "/api/projects/{project_id}/metric-groups",
    response_model=MetricGroupOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    project_id: int,
    body: MetricGroupCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> MetricGroupOut:
    proj = await db.execute(select(Project).where(Project.id == project_id))
    if proj.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    group = MetricGroup(
        project_id=project_id,
        name=body.name,
        group_type=body.group_type,
        prompt_template=body.prompt_template,
    )
    db.add(group)
    await db.flush()
    await db.refresh(group, ["items"])
    return _group_to_out(group)


@router.get("/api/metric-groups/{group_id}", response_model=MetricGroupOut)
async def get_group(
    group_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> MetricGroupOut:
    return _group_to_out(await _get_group_or_404(db, group_id))


@router.patch("/api/metric-groups/{group_id}", response_model=MetricGroupOut)
async def update_group(
    group_id: int,
    body: MetricGroupUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> MetricGroupOut:
    group = await _get_group_or_404(db, group_id)

    if body.name is not None:
        group.name = body.name
    if body.prompt_template is not None:
        group.prompt_template = body.prompt_template

    return _group_to_out(group)


@router.delete("/api/metric-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> None:
    group = await _get_group_or_404(db, group_id)

    # Check if any item in this group has analysis results (RESTRICT FK would fire)
    item_ids = [item.id for item in group.items]
    if item_ids:
        result_count = await db.execute(
            select(func.count())
            .select_from(AnalysisResult)
            .where(AnalysisResult.metric_item_id.in_(item_ids))
        )
        count = result_count.scalar_one()
        if count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot delete group: {count} analysis result(s) reference its items. "
                    "Deactivate items instead of deleting the group."
                ),
            )

    await db.delete(group)


# ── Item routes ───────────────────────────────────────────────────────────────

@router.get("/api/metric-groups/{group_id}/items", response_model=list[MetricItemOut])
async def list_items(
    group_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> list[MetricItemOut]:
    group = await _get_group_or_404(db, group_id)
    return sorted(
        [MetricItemOut.model_validate(i) for i in group.items],
        key=lambda x: x.position,
    )


@router.post(
    "/api/metric-groups/{group_id}/items",
    response_model=MetricItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    group_id: int,
    body: MetricItemCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> MetricItem:
    # Verify group exists
    await _get_group_or_404(db, group_id)

    position = await _next_position(db, group_id)
    item = MetricItem(
        metric_group_id=group_id,
        position=position,
        name=body.name,
        description=body.description,
    )
    db.add(item)
    await db.flush()
    return item


@router.patch("/api/metric-items/{item_id}", response_model=MetricItemOut)
async def update_item(
    item_id: int,
    body: MetricItemUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> MetricItem:
    item = await _get_item_or_404(db, item_id)

    if body.name is not None:
        item.name = body.name
    if body.clear_description:
        item.description = None
    elif body.description is not None:
        item.description = body.description

    return item


@router.delete("/api/metric-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_item(
    item_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> None:
    """
    Soft-delete: sets is_active=False.
    The item is excluded from new analyses but preserved for historical results.
    Hard deletion is blocked by RESTRICT FK on AnalysisResult.metric_item_id.
    """
    item = await _get_item_or_404(db, item_id)
    item.is_active = False
