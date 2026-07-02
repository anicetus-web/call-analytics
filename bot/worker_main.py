"""
Dedicated worker entrypoint.

Runs the bot + task-queue worker without spinning up an HTTP server for API
routes. Exposes a tiny /health endpoint so docker-compose healthchecks pass.

Usage:
    python -m bot.worker_main
"""

import asyncio
import logging
import signal
from contextlib import suppress

from config import settings
from bot.runtime import BotRuntime

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")


async def main() -> None:
    if not (settings.RUN_BOT or settings.RUN_WORKER):
        logger.error(
            "worker_main started but both RUN_BOT and RUN_WORKER are false — exiting"
        )
        return

    runtime = BotRuntime()
    await runtime.start()

    # Minimal /health + /internal/enqueue endpoint so docker healthchecks pass
    # and the api container can signal new calls to process.
    from api.routes.internal import internal_router as _internal_router
    from fastapi import FastAPI as _FastAPI
    _fastapp = _FastAPI()
    _fastapp.include_router(_internal_router)

    @_fastapp.get("/health")
    async def _health_fast() -> dict:
        return {"status": "ok"}

    import uvicorn
    config = uvicorn.Config(_fastapp, host="0.0.0.0", port=settings.API_PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="worker-health-server")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    logger.info("Shutting down worker process...")
    await runtime.stop()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
