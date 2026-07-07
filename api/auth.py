"""
JWT authentication for the admin web panel.

Admins authenticate with login + password → receive a JWT access token.
The token is verified on every protected endpoint via Depends(require_admin).

Token payload: {"sub": str(user_id), "role": "admin"}

Only ADMIN-role users can obtain tokens.
Token expiry: settings.JWT_EXPIRE_MINUTES (default 1 day).

Login brute-force protection:
  - In-memory sliding window limits failed attempts per login to 5 within 15 minutes.
  - After the limit is hit, all attempts for that login are rejected with 429 until
    the window slides. This protects against targeted password brute-force without
    requiring an external dependency like slowapi or Redis.
  - The limiter resets on process restart (acceptable for a 2-admin system).
"""

import time
import collections
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import User, UserRole

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

ALGORITHM = "HS256"

# ── Login rate limiter ────────────────────────────────────────────────────────
# Keyed by login name. Each key stores a deque of timestamps of recent FAILED
# attempts. Successful logins clear the deque for that login.
_MAX_FAILED_ATTEMPTS = 5
_WINDOW_SECONDS = 15 * 60  # 15 minutes
_failed_attempts: dict[str, collections.deque] = {}
# Keys are attacker-controlled login strings; without a sweep the dict would grow
# without bound under a probe of random logins (memory DoS). Sweep expired keys
# whenever the dict gets large.
_SWEEP_THRESHOLD = 10_000


def _check_rate_limit(login: str) -> None:
    """Raise 429 if the login has too many recent failed attempts."""
    dq = _failed_attempts.get(login)
    if dq is None:
        return
    now = time.monotonic()
    # Discard expired entries
    while dq and dq[0] < now - _WINDOW_SECONDS:
        dq.popleft()
    if not dq:
        _failed_attempts.pop(login, None)
        return
    if len(dq) >= _MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
        )


def _record_failure(login: str) -> None:
    now = time.monotonic()
    if len(_failed_attempts) >= _SWEEP_THRESHOLD:
        cutoff = now - _WINDOW_SECONDS
        for key in [k for k, v in _failed_attempts.items() if not v or v[-1] < cutoff]:
            _failed_attempts.pop(key, None)
    dq = _failed_attempts.setdefault(login, collections.deque())
    dq.append(now)


def _clear_failures(login: str) -> None:
    _failed_attempts.pop(login, None)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: int
    role: UserRole


# ── Password helpers ─────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_access_token(user_id: int, role: UserRole) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> TokenData:
    """
    Decode and validate a JWT token.
    Raises HTTPException 401 on any invalid or expired token.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str | None = payload.get("sub")
        role_str: str | None = payload.get("role")

        if user_id_str is None or role_str is None:
            raise ValueError("Missing claims")
        if "exp" not in payload:
            raise ValueError("Missing exp claim")

        return TokenData(user_id=int(user_id_str), role=UserRole(role_str))

    except (JWTError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── Dependencies ──────────────────────────────────────────────────────────────

async def require_admin(token: Annotated[str, Depends(_oauth2_scheme)]) -> TokenData:
    """
    FastAPI dependency: validates JWT and asserts ADMIN role.
    Use as: current = Depends(require_admin)
    """
    token_data = _decode_token(token)
    if token_data.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return token_data


# ── Auth endpoint logic ───────────────────────────────────────────────────────

async def authenticate_admin(
    form: OAuth2PasswordRequestForm,
    db: AsyncSession,
) -> TokenResponse:
    """
    Validate credentials and return a JWT token.
    Raises HTTPException 401 if credentials are invalid or user is not an admin.
    Raises HTTPException 429 if too many failed attempts for this login.
    Called from the /api/auth/token POST route.
    """
    login = form.username
    _check_rate_limit(login)

    result = await db.execute(
        select(User).where(User.login == login, User.role == UserRole.ADMIN)
    )
    user: User | None = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        _record_failure(login)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(form.password, user.password_hash):
        _record_failure(login)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _clear_failures(login)
    token = create_access_token(user_id=user.id, role=user.role)
    return TokenResponse(access_token=token)
