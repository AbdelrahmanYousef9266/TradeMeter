"""
Async TCP server — receives pipe-delimited OHLCV messages from NinjaTrader 8
and routes them to Redis Streams + pub/sub for downstream processing.

One persistent TCP connection per NinjaTrader session carries many messages.
Token validation runs once per connection and is then cached locally in the
coroutine scope.  A Redis cache avoids bcrypt re-verification on reconnect.
"""

import asyncio
import hashlib
import json
import logging
import uuid as _uuid
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

from app.core.security import verify_nt_token
from app.core.redis import publish_tick, cache_latest_tick
from app.models.tick import RawMessage

logger = logging.getLogger(__name__)

# Key TTL: 1 hour.  Low-security trade-off: we store sha256(token) → user_id,
# never the plain token itself, to avoid leaking credentials into Redis.
_TOKEN_CACHE_TTL = 3600


def _token_cache_key(token: str) -> str:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"nt_token_cache:{digest}"


async def _resolve_token(
    token: str,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> str | None:
    """
    Return the user_id (as str) matching the given plain NT token, or None.

    Strategy:
    1. Fast path — check Redis cache (sha256(token) → user_id).
    2. Slow path — filter by stored prefix, then bcrypt-verify candidates.
       Cache the result on success for future reconnections.
    """
    token = token.strip()
    cache_key = _token_cache_key(token)
    cached = await redis_client.get(cache_key)
    if cached:
        logger.debug("TCP: token resolved from Redis cache → user_id=%s", cached)
        return cached

    # Tokens are "TM-XXXXXX" (9 chars total).
    # nt_token_prefix in the DB holds the FULL 9-char token for exact matching.
    logger.debug("TCP: resolving token bytes=%r len=%d", token, len(token))

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, nt_token_hash, email FROM users "
            "WHERE nt_token_prefix = $1 AND nt_token_hash IS NOT NULL",
            token,  # exact match against full stored token
        )

    if not rows:
        # No exact match — log DB state to help diagnose stale tokens.
        async with db_pool.acquire() as conn:
            all_rows = await conn.fetch(
                "SELECT email, nt_token_prefix, nt_token_hash IS NOT NULL AS has_hash FROM users"
            )
        logger.warning(
            "TCP: no user found for token %r — DB state: %s",
            token,
            [dict(r) for r in all_rows],
        )
        return None

    for row in rows:
        if verify_nt_token(token, row["nt_token_hash"]):
            user_id = str(row["id"])
            await redis_client.set(cache_key, user_id, ex=_TOKEN_CACHE_TTL)
            logger.info("TCP: token verified for %s → user_id=%s", row["email"], user_id)
            return user_id

    # Exact prefix matched but bcrypt failed — hash mismatch, token likely rotated.
    logger.warning(
        "TCP: token %r found in DB but bcrypt verification failed — "
        "user should refresh token on the Connect page",
        token,
    )
    return None


async def _mark_connected(user_id: str, db_pool: asyncpg.Pool) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE users
               SET nt_connected = TRUE, nt_last_seen = $1
               WHERE id = $2""",
            datetime.now(tz=timezone.utc),
            _uuid.UUID(user_id),
        )


async def _mark_disconnected(user_id: str, db_pool: asyncpg.Pool) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET nt_connected = FALSE WHERE id = $1",
            _uuid.UUID(user_id),
        )


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    """Handle one NinjaTrader TCP connection for its full lifetime."""
    addr = writer.get_extra_info("peername")
    logger.info("TCP: new connection from %s", addr)

    user_id: str | None = None
    buffer = ""

    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break  # Client closed the connection

            buffer += chunk.decode("utf-8", errors="replace")

            # Process every complete newline-terminated message in the buffer.
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                # ── Parse ──────────────────────────────────────────────────
                try:
                    msg = RawMessage.parse(line)
                except ValueError as exc:
                    logger.warning("TCP: malformed message from %s: %s", addr, exc)
                    continue

                # ── Validate token (once per connection) ───────────────────
                if user_id is None:
                    user_id = await _resolve_token(msg.token, db_pool, redis_client)
                    if user_id is None:
                        logger.warning(
                            "TCP: unknown token from %s: %s***",
                            addr, msg.token[:6],
                        )
                        # Keep reading — the user may reconnect with a correct token.
                        continue
                    await _mark_connected(user_id, db_pool)
                    logger.info("TCP: token validated → user_id=%s", user_id)

                # ── Publish ────────────────────────────────────────────────
                tick = {
                    "symbol":    msg.symbol,
                    "timestamp": msg.timestamp.isoformat(),
                    "open":      msg.open,
                    "high":      msg.high,
                    "low":       msg.low,
                    "close":     msg.close,
                    "volume":    msg.volume,
                    "bar_type":  msg.bar_type,
                }
                try:
                    await publish_tick(redis_client, user_id, tick)
                    await cache_latest_tick(redis_client, user_id, tick)
                except Exception as exc:
                    logger.error("TCP: Redis publish failed: %s", exc)

    except asyncio.IncompleteReadError:
        pass
    except Exception as exc:
        logger.error("TCP: unexpected error from %s: %s", addr, exc)
    finally:
        logger.info("TCP: connection closed from %s", addr)
        if user_id:
            try:
                await _mark_disconnected(user_id, db_pool)
            except Exception:
                pass
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def start_tcp_server(
    host: str,
    port: int,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    """Start the asyncio TCP server and run forever."""

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        await handle_client(reader, writer, db_pool, redis_client)

    server = await asyncio.start_server(_handler, host, port)
    logger.info("TradeMeter TCP listener started on %s:%s", host, port)
    async with server:
        await server.serve_forever()
