"""
FastAPI application entry point.

Startup sequence (lifespan):
  1. Schema is owned by Alembic (the `migrate` compose service runs
     `alembic upgrade head` exactly once before api/worker start).
  2. Start aiogram bot as background task (only if RUN_BOT=true)
  3. Start call processing queue worker (only if RUN_WORKER=true)

Shutdown sequence:
  1. Cancel worker task
  2. Cancel bot polling task
  3. Close aiogram bot session

When RUN_BOT and RUN_WORKER are both false (the default for the api compose
service), only the HTTP API runs — lifespan starts and stops a no-op BotRuntime.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from bot.runtime import BotRuntime
from api.auth import authenticate_admin, TokenResponse
from api.routes.users import router as users_router
from api.routes.projects import router as projects_router
from api.routes.metrics import router as metrics_router
from api.routes.calls import router as calls_router
from api.routes.analytics import router as analytics_router

logger = logging.getLogger(__name__)

# Filled in during lifespan startup
_runtime: BotRuntime | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _runtime

    # Schema management is owned by Alembic (the `migrate` compose service runs
    # `alembic upgrade head` exactly once before api/worker start). init_db()
    # is intentionally not called here to avoid drifting from migrations.

    _runtime = BotRuntime()
    await _runtime.start()
    logger.info("Application startup complete")
    yield

    logger.info("Shutting down...")
    await _runtime.stop()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Call Analytics API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
    )

    # CORS — origins come from config so production domains can be set via .env
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth + business routers are only mounted in API-role processes. In a worker-only
    # process (RUN_API=false) the ASGI app still exists to drive lifespan (bot+worker),
    # but it exposes only /health, so accidentally hitting the worker port can't
    # bypass the dedicated API instance or duplicate routes.
    if settings.RUN_API:
        from fastapi import Depends, HTTPException
        from fastapi.security import OAuth2PasswordRequestForm
        from pydantic import BaseModel
        from sqlalchemy import select
        from database import get_db, User
        from sqlalchemy.ext.asyncio import AsyncSession
        from api.auth import require_admin, TokenData

        @app.post("/api/auth/token", response_model=TokenResponse, tags=["auth"])
        async def login(
            form: OAuth2PasswordRequestForm = Depends(),
            db: AsyncSession = Depends(get_db),
        ) -> TokenResponse:
            return await authenticate_admin(form, db)

        class CurrentUserOut(BaseModel):
            id: int
            name: str
            login: str | None

        @app.get("/api/auth/me", response_model=CurrentUserOut, tags=["auth"])
        async def me(
            current: TokenData = Depends(require_admin),
            db: AsyncSession = Depends(get_db),
        ) -> CurrentUserOut:
            result = await db.execute(select(User).where(User.id == current.user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            return CurrentUserOut(id=user.id, name=user.name, login=user.login)

        app.include_router(users_router)
        app.include_router(projects_router)
        app.include_router(metrics_router)
        app.include_router(calls_router)
        app.include_router(analytics_router)
        from api.routes.internal import internal_router
        app.include_router(internal_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
