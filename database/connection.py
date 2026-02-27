"""
Async database connection pool for Neon (PostgreSQL via asyncpg).
Also provides a sync engine URL for APScheduler's SQLAlchemy jobstore.
"""
import asyncpg
import asyncio
import logging
from config import NEON_ASYNC_URL, NEON_DATABASE_URL

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return the global connection pool, creating it if needed."""
    global _pool
    if _pool is None:
        # asyncpg needs plain "postgresql://" — strip SQLAlchemy "+asyncpg" driver prefix
        raw_url = NEON_ASYNC_URL.replace("postgresql+asyncpg://", "postgresql://")
        _pool = await asyncpg.create_pool(
            dsn=raw_url,
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
        logger.info("✅ Database pool created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


async def run_migrations() -> None:
    """Run the SQL migrations file on startup."""
    import pathlib
    sql_path = pathlib.Path(__file__).parent / "migrations.sql"
    if not sql_path.exists():
        logger.warning("migrations.sql not found — skipping")
        return

    sql = sql_path.read_text(encoding="utf-8")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql)
    logger.info("✅ Migrations applied")


# Sync DB URL for APScheduler / SQLAlchemy (strips asyncpg driver)
SYNC_DB_URL = NEON_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
