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


async def upsert_user(conn, email: str, google_id: str) -> dict:
    """
    Insert a new user or update google_id if the email already exists.
    Returns the full user row as a dict.
    """
    row = await conn.fetchrow(
        """INSERT INTO users (email, google_id)
           VALUES ($1, $2)
           ON CONFLICT (email) DO UPDATE
               SET google_id = EXCLUDED.google_id
           RETURNING *""",
        email, google_id,
    )
    return dict(row)


def _is_comment_only(stmt: str) -> bool:
    """True if a split chunk has no executable SQL (only -- comments / blanks).

    A `;` inside a comment can split the file into a comment-only chunk, and
    asyncpg's execute() of a bare comment raises AttributeError (not a
    PostgresError), which would crash startup. We skip such chunks defensively.
    """
    for line in stmt.splitlines():
        s = line.strip()
        if s and not s.startswith("--"):
            return False
    return True


async def _run_migration(pool: asyncpg.Pool, sql_path: str) -> None:
    """Execute a single migration file, one statement per connection."""
    with open(sql_path, encoding="utf-8") as fh:
        sql = fh.read()

    statements = [s.strip() for s in sql.split(";") if s.strip() and not _is_comment_only(s)]
    for stmt in statements:
        async with pool.acquire() as conn:
            try:
                await conn.execute(stmt)
            except asyncpg.PostgresError as exc:
                logger.warning("Migration statement skipped: %s | %s", exc, stmt[:80])


async def init_db(pool: asyncpg.Pool) -> None:
    """
    Execute all migration SQL files in order.
    Each file is idempotent (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
    """
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")

    for filename in sorted(os.listdir(migrations_dir)):
        if not filename.endswith(".sql"):
            continue
        sql_path = os.path.join(migrations_dir, filename)
        await _run_migration(pool, sql_path)
        logger.info("Migration applied: %s", filename)

    logger.info("Database schema initialised")
