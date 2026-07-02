"""
Internal API endpoints — not exposed in OpenAPI docs.
Used for inter-process communication (e.g. API → worker enqueue signal).
"""

import hmac

from fastapi import APIRouter, Header, HTTPException, status

from config import settings
from services import task_queue

internal_router = APIRouter(prefix="/internal", include_in_schema=False)


@internal_router.post("/enqueue/{call_id}")
async def internal_enqueue(
    call_id: int,
    x_bot_secret: str | None = Header(default=None),
) -> dict:
    """Signal the worker to enqueue a call. Protected by BOT_SECRET."""
    if x_bot_secret is None or not hmac.compare_digest(x_bot_secret, settings.BOT_SECRET):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    ok = task_queue.enqueue(call_id)
    return {"enqueued": ok, "call_id": call_id}
