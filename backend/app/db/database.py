import os
import logging
import asyncpg
from fastapi import Request
from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level pool reference — set during lifespan startup.
_pool: asyncpg.Pool | None = None


async def create_pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
    )
    logger.info("Database pool created")
    return pool


async def get_db(request: Request):
    """FastAPI dependency — yields an asyncpg connection from the pool."""
    async with request.app.state.db_pool.acquire() as conn:
        yield conn


async def init_db(pool: asyncpg.Pool) -> None:
    """
    Execute the initial migration SQL.
    Uses IF NOT EXISTS throughout so it is safe to run on every startup.
    """
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    sql_path = os.path.join(migrations_dir, "001_initial.sql")

    with open(sql_path, encoding="utf-8") as fh:
        sql = fh.read()

    async with pool.acquire() as conn:
        # Split on semicolons so we can execute each statement individually —
        # asyncpg's execute() handles multi-statement strings but some
        # TimescaleDB DDL (SELECT create_hypertable) needs isolation.
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            try:
                await conn.execute(stmt)
            except asyncpg.PostgresError as exc:
                # Log but don't re-raise — most errors here are
                # "already exists" races on concurrent startups.
                logger.warning("Migration statement skipped: %s | %s", exc, stmt[:80])

    logger.info("Database schema initialised")
