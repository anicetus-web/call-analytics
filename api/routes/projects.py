"""
Project CRUD + member management endpoints (admin-only).

Projects are never hard-deleted — they are archived (is_active=False).
A project can only be deactivated if it has no active calls in non-terminal states.

Members are the managers assigned to a project. A manager can belong to
multiple projects.

Endpoints:
  GET    /api/projects               — list all projects (active by default)
  POST   /api/projects               — create project
  GET    /api/projects/{id}          — get project with members
  PATCH  /api/projects/{id}          — update name/description
  DELETE /api/projects/{id}          — deactivate (soft delete)

  GET    /api/projects/{id}/members          — list members
  POST   /api/projects/{id}/members          — add member
  DELETE /api/projects/{id}/members/{uid}    — remove member
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin, TokenData
from database import (
    Project, ProjectMember, User, UserRole, Call, CallStatus, get_db
)

router = APIRouter(prefix="/api/projects", tags=["projects"])

_TERMINAL_STATUSES = (CallStatus.DONE, CallStatus.ERROR)


# ── Schemas ───────────────────────────────────────────────────────────────────

class MemberOut(BaseModel):
    id: int
    name: str
    telegram_id: int | None

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None
    is_active: bool
    created_by: int
    members: list[MemberOut] = []

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None)
    clear_description: bool = False  # set true to explicitly clear description


class AddMemberBody(BaseModel):
    user_id: int


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_project_or_404(db: AsyncSession, project_id: int) -> Project:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.members).selectinload(ProjectMember.user))
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _project_to_out(project: Project) -> ProjectOut:
    members = [
        MemberOut(
            id=pm.user.id,
            name=pm.user.name,
            telegram_id=pm.user.telegram_id,
        )
        for pm in project.members
        if pm.user is not None
    ]
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        is_active=project.is_active,
        created_by=project.created_by,
        members=members,
    )


# ── Project routes ────────────────────────────────────────────────────────────

@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
    include_inactive: bool = Query(default=False),
) -> list[ProjectOut]:
    q = select(Project).options(
        selectinload(Project.members).selectinload(ProjectMember.user)
    )
    if not include_inactive:
        q = q.where(Project.is_active.is_(True))
    q = q.order_by(Project.name)
    result = await db.execute(q)
    return [_project_to_out(p) for p in result.scalars().all()]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[TokenData, Depends(require_admin)],
) -> ProjectOut:
    project = Project(
        name=body.name,
        description=body.description,
        created_by=current.user_id,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        is_active=project.is_active,
        created_by=project.created_by,
        members=[],
    )


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> ProjectOut:
    return _project_to_out(await _get_project_or_404(db, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> ProjectOut:
    project = await _get_project_or_404(db, project_id)

    if body.name is not None:
        project.name = body.name
    if body.clear_description:
        project.description = None
    elif body.description is not None:
        project.description = body.description

    return _project_to_out(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> None:
    project = await _get_project_or_404(db, project_id)

    if not project.is_active:
        return  # already deactivated — idempotent

    # Block deactivation while calls are actively being processed
    active_result = await db.execute(
        select(func.count())
        .select_from(Call)
        .where(
            Call.project_id == project_id,
            Call.status.not_in(_TERMINAL_STATUSES),
        )
    )
    active_count = active_result.scalar_one()
    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot archive project: {active_count} call(s) are still being processed.",
        )

    project.is_active = False


# ── Member routes ─────────────────────────────────────────────────────────────

@router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> list[MemberOut]:
    project = await _get_project_or_404(db, project_id)
    return [
        MemberOut(id=pm.user.id, name=pm.user.name, telegram_id=pm.user.telegram_id)
        for pm in project.members
        if pm.user is not None
    ]


@router.post("/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    project_id: int,
    body: AddMemberBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> dict:
    project = await _get_project_or_404(db, project_id)

    # Verify user exists and is a manager
    user_result = await db.execute(
        select(User).where(User.id == body.user_id, User.role == UserRole.MANAGER)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Manager with id={body.user_id} not found",
        )

    # Check not already a member
    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == body.user_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this project",
        )

    db.add(ProjectMember(project_id=project_id, user_id=body.user_id))
    return {"project_id": project_id, "user_id": body.user_id}


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: int,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> None:
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this project",
        )
    await db.delete(membership)
