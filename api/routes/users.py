"""
Manager CRUD endpoints (admin-only).

Managers are created by admins and use Telegram to interact with the bot.
Only MANAGER-role users are returned/managed here — admins manage themselves
via direct DB access or a separate setup script.

Endpoints:
  GET    /api/users          — list all managers
  POST   /api/users          — create a manager
  GET    /api/users/{id}     — get one manager
  PATCH  /api/users/{id}     — update name or telegram_id
  DELETE /api/users/{id}     — delete manager (only if no calls attached)
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin, TokenData
from database import User, UserRole, Call, get_db

router = APIRouter(prefix="/api/users", tags=["users"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ManagerOut(BaseModel):
    id: int
    name: str
    telegram_id: int | None
    login: str | None
    # Telegram bot session (see bot/handlers.py /start, /finish). session_started_at
    # is the source of truth for "active" — session_project_id can be stale once a
    # session ends, since only session_started_at is guaranteed to be cleared then.
    session_project_id: int | None
    session_started_at: datetime | None

    model_config = {"from_attributes": True}


class ManagerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    telegram_id: int
    login: str | None = Field(default=None, max_length=255)


class ManagerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    telegram_id: int | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_manager_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.role == UserRole.MANAGER)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
    return user


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ManagerOut])
async def list_managers(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> list[User]:
    result = await db.execute(
        select(User)
        .where(User.role == UserRole.MANAGER)
        .order_by(User.name)
    )
    return result.scalars().all()


@router.post("", response_model=ManagerOut, status_code=status.HTTP_201_CREATED)
async def create_manager(
    body: ManagerCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> User:
    # Check telegram_id uniqueness
    existing = await db.execute(
        select(User).where(User.telegram_id == body.telegram_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with telegram_id={body.telegram_id} already exists",
        )

    user = User(
        name=body.name,
        telegram_id=body.telegram_id,
        login=body.login,
        role=UserRole.MANAGER,
    )
    db.add(user)
    await db.flush()  # populate user.id before returning
    return user


@router.get("/{user_id}", response_model=ManagerOut)
async def get_manager(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> User:
    return await _get_manager_or_404(db, user_id)


@router.patch("/{user_id}", response_model=ManagerOut)
async def update_manager(
    user_id: int,
    body: ManagerUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> User:
    user = await _get_manager_or_404(db, user_id)

    if body.name is not None:
        user.name = body.name

    if body.telegram_id is not None and body.telegram_id != user.telegram_id:
        conflict = await db.execute(
            select(User).where(User.telegram_id == body.telegram_id)
        )
        if conflict.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"telegram_id={body.telegram_id} already taken",
            )
        user.telegram_id = body.telegram_id

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_manager(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[TokenData, Depends(require_admin)],
) -> None:
    user = await _get_manager_or_404(db, user_id)

    # Prevent deletion if manager has any calls (FK is RESTRICT on calls.user_id)
    call_count_result = await db.execute(
        select(func.count()).select_from(Call).where(Call.user_id == user_id)
    )
    call_count = call_count_result.scalar_one()
    if call_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete manager with {call_count} existing call(s). Reassign or delete calls first.",
        )

    await db.delete(user)
