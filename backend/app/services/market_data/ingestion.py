"""
Redis Streams consumer — reads from 'market:raw', writes bar closes to
TimescaleDB, and computes features for downstream ML use.

Only bar-close messages (bar_type != 'tick') are written to the database.
Tick messages flow through Redis only (for live WebSocket) and are not stored.
"""

import asyncio
import json
import logging
import uuid as _uuid
from datetime import datetime

import asyncpg
import redis.asyncio as aioredis

from app.models.tick import Tick
from app.services.market_data.features import get_engine

logger = logging.getLogger(__name__)

_STREAM_KEY = "market:raw"


async def write_tick_to_db(conn: asyncpg.Connection, tick: Tick) -> None:
    """INSERT a completed bar into the TimescaleDB ticks hypertable."""
    await conn.execute(
        """INSERT INTO ticks (time, user_id, symbol, open, high, low, close, volume, bar_type)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        tick.time,
        tick.user_id,
        tick.symbol,
        tick.open,
        tick.high,
        tick.low,
        tick.close,
        tick.volume,
        tick.bar_type,
    )


async def _process_entry(
    fields: dict,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    """Parse a Redis Stream entry and handle it appropriately."""
    try:
        # All stream field values arrive as strings.
        tick = Tick(
            time=datetime.fromisoformat(fields["timestamp"]),
            user_id=_uuid.UUID(fields["user_id"]),
            symbol=fields["symbol"],
            open=float(fields["open"]),
            high=float(fields["high"]),
            low=float(fields["low"]),
            close=float(fields["close"]),
            volume=int(fields["volume"]),
            bar_type=fields["bar_type"],
        )
    except (KeyError, ValueError) as exc:
        logger.warning("Ingestion: bad stream entry: %s | %s", exc, fields)
        return

    # Ticks are published to Redis but not persisted — too frequent and
    # would bloat the hypertable without adding analytical value.
    if tick.bar_type == "tick":
        return

    # ── Write bar close to TimescaleDB ────────────────────────────────────
    try:
        async with db_pool.acquire() as conn:
            await write_tick_to_db(conn, tick)
    except asyncpg.PostgresError as exc:
        logger.error("Ingestion: DB write failed: %s", exc)
        return

    # ── Compute features (result cached in Redis for Phase 3 ML) ──────────
    try:
        features = get_engine(str(tick.user_id)).update(tick)
        if features is not None:
            await redis_client.set(
                f"features:{tick.user_id}",
                json.dumps(features),
                ex=300,
            )
    except Exception as exc:
        logger.error("Ingestion: feature computation failed: %s", exc)


async def consume_stream(
    redis_client: aioredis.Redis,
    db_pool: asyncpg.Pool,
) -> None:
    """
    Infinite loop — reads new entries from 'market:raw' and processes them.

    Uses XREAD with a 1-second block so the loop yields when the stream is idle.
    '$' means only messages that arrive after this consumer starts are processed.
    """
    last_id = "$"
    logger.info("Ingestion consumer started on stream '%s'", _STREAM_KEY)

    while True:
        try:
            result = await redis_client.xread(
                {_STREAM_KEY: last_id},
                block=1000,
                count=100,
            )
            if not result:
                continue

            for _stream_name, entries in result:
                for entry_id, fields in entries:
                    last_id = entry_id
                    await _process_entry(fields, db_pool, redis_client)

        except asyncio.CancelledError:
            logger.info("Ingestion consumer cancelled")
            break
        except Exception as exc:
            logger.error("Ingestion: stream read error: %s", exc)
            await asyncio.sleep(1)
