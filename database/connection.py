from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.base import Base
from config import settings

# Connection pool sizing:
# Each process (API + each Celery worker) creates its own engine with its own pool.
# Peak connections per process = pool_size + max_overflow = 5 + 10 = 15.
# Formula: (pool_size + max_overflow) * total_processes < max_connections
# With 1 API + 3 workers = 4 processes: 15 * 4 = 60 < 100 (PG default) — safe.
# Adjust pool_size in config if adding more workers; keep the formula result < 80
# to leave headroom for admin tools (psql, pgAdmin).
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    # Commits on every request including GETs (empty commit is cheap).
    # If read-only performance becomes an issue — add get_db_readonly() without commit.
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# WARNING: dev only — does not handle migrations.
# Use Alembic for any schema changes in production.
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
