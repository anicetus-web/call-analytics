"""
One-off backfill: apply the universal 8-stage "Этапы продающей встречи"
metric group (services/default_metrics.py) to every EXISTING project. New
projects get it automatically at creation (api/routes/projects.py). Safe to
re-run — ensure_default_metric_group() is idempotent.

Usage: python -m scripts.backfill_default_metrics
"""
import asyncio

from sqlalchemy import select

from database import AsyncSessionLocal, Project
from services.default_metrics import ensure_default_metric_group


async def backfill() -> None:
    async with AsyncSessionLocal() as db:
        projects = (await db.execute(select(Project))).scalars().all()
        for project in projects:
            group = await ensure_default_metric_group(db, project.id)
            print(f"Project {project.id} ({project.name!r}) -> group id={group.id}")
        await db.commit()
        print(f"Done: {len(projects)} project(s) processed.")


if __name__ == "__main__":
    asyncio.run(backfill())
