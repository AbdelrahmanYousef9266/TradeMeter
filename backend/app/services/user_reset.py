"""
Scoped clean-slate reset for a single user.

Deletes a user's *learned state and derived history* — predictions, Champion/
Challenger history, model levels/XP, and all persisted model weights (River +
LSTM). Raw OHLCV bars (`ticks`) are deleted only when explicitly requested,
because the price data itself is not biased — only the simulated trades and
labels derived from it were (the look-ahead-bias era). Keeping bars lets the
user retrain cleanly from real price history.

Every statement is parameterized and scoped to a single user_id. Used by both
the CLI script (scripts/reset_user_data.py) and the POST /admin/reset-my-data
endpoint so the two paths can never drift.
"""

import logging

logger = logging.getLogger(__name__)


def _deleted_count(command_tag: str) -> int:
    """Parse asyncpg's 'DELETE <n>' command tag into an int (0 on anything odd)."""
    try:
        return int(command_tag.split()[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


async def count_user_data(conn, user_id, include_bars: bool) -> dict[str, int]:
    """Row counts for everything a reset would delete — no mutation."""
    counts = {
        "predictions":  await conn.fetchval("SELECT COUNT(*) FROM predictions  WHERE user_id = $1", user_id),
        "cc_history":   await conn.fetchval("SELECT COUNT(*) FROM cc_history   WHERE user_id = $1", user_id),
        "model_levels": await conn.fetchval("SELECT COUNT(*) FROM model_levels WHERE user_id = $1", user_id),
        "model_state":  await conn.fetchval("SELECT COUNT(*) FROM model_state  WHERE user_id = $1", user_id),
    }
    if include_bars:
        counts["ticks"] = await conn.fetchval("SELECT COUNT(*) FROM ticks WHERE user_id = $1", user_id)
    return counts


async def reset_user_data(conn, user_id, include_bars: bool) -> dict[str, int]:
    """
    Delete the user's learned state (and optionally their bars) in one
    transaction. Returns the number of rows deleted per table.
    """
    deleted: dict[str, int] = {}
    async with conn.transaction():
        deleted["predictions"]  = _deleted_count(await conn.execute("DELETE FROM predictions  WHERE user_id = $1", user_id))
        deleted["cc_history"]   = _deleted_count(await conn.execute("DELETE FROM cc_history   WHERE user_id = $1", user_id))
        deleted["model_levels"] = _deleted_count(await conn.execute("DELETE FROM model_levels WHERE user_id = $1", user_id))
        deleted["model_state"]  = _deleted_count(await conn.execute("DELETE FROM model_state  WHERE user_id = $1", user_id))
        if include_bars:
            deleted["ticks"] = _deleted_count(await conn.execute("DELETE FROM ticks WHERE user_id = $1", user_id))
    logger.info("Reset user %s data (include_bars=%s): %s", user_id, include_bars, deleted)
    return deleted


def purge_in_memory_state(user_id: str) -> None:
    """
    Evict a user's in-memory pipeline/feature/ingestion state on a live backend.

    Without this, the running pipeline would keep its old levels + weights and
    re-persist them on the next bar, silently undoing the DB reset. After purge,
    the next bar rebuilds everything from the (now-empty) DB: fresh models at
    level 1, dormant LSTM, watermark reseeded from whatever bars remain.

    Best-effort and idempotent — a user with no active state is a no-op. Only
    needed by the API path; the CLI script runs in a separate process.
    """
    from app.services.ml.pipeline import _pipelines, _pipeline_locks
    from app.services.market_data.features import _engines
    from app.services.market_data import ingestion as ing

    for registry in (
        _pipelines, _pipeline_locks, _engines,
        ing._bar_state, ing._last_bar_time,
        ing._training_mode, ing._training_bar_count, ing._training_sessions,
    ):
        registry.pop(user_id, None)
    logger.info("Purged in-memory state for user %s", user_id)
