"""
Async TCP server — receives pipe-delimited OHLCV messages from NinjaTrader 8
and routes them to Redis Streams + pub/sub for downstream processing.

One persistent TCP connection per NinjaTrader session carries many messages.
Token validation runs once per connection and is then cached locally in the
coroutine scope.  A Redis cache avoids bcrypt re-verification on reconnect.
"""

import asyncio
import json
import logging
import uuid as _uuid
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

from app.core.security import (
    verify_nt_token,
    nt_token_lookup_hash,
    nt_token_cache_key,
)
from app.core.redis import publish_tick, cache_latest_tick
from app.models.tick import RawMessage
from app.services.market_data.ingestion import is_ingestion_armed, note_bar_refused

logger = logging.getLogger(__name__)

# Key TTL: 1 hour.  Low-security trade-off: we store sha256(token) → user_id,
# never the plain token itself, to avoid leaking credentials into Redis.
_TOKEN_CACHE_TTL = 3600

# ── Abuse limits (the TCP port is internet-exposed for remote NinjaTrader) ──
# A valid message is ~100 bytes. These bounds stop a hostile or buggy client
# from exhausting memory (an endless stream with no newline) or hammering the
# token path (a brute-force / connect-flood DoS) without any throttle.
_MAX_LINE_BYTES       = 8192   # a single message this long is malformed → drop the connection
_MAX_BUFFER_BYTES     = 65536  # unparsed backlog cap; exceeding it means no newline is coming
_MAX_AUTH_FAILURES    = 10     # bad tokens tolerated before we close the connection
_MAX_PREAUTH_MESSAGES = 50     # total lines accepted before a token must resolve


async def _resolve_token(
    token: str,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> str | None:
    """
    Return the user_id (as str) matching the given plain NT token, or None.

    Strategy:
    1. Fast path — check Redis cache (sha256(token) → user_id).
    2. Slow path — look up the row by the SHA-256 lookup index, then
       bcrypt-verify. Cache the result on success for future reconnections.

    The plaintext token is never persisted and never logged — only a short,
    non-reversible fingerprint of its SHA-256 digest appears in diagnostics.
    """
    token = token.strip()
    lookup = nt_token_lookup_hash(token)
    fingerprint = lookup[:8]   # safe, non-reversible identifier for logs

    cache_key = nt_token_cache_key(lookup)
    cached = await redis_client.get(cache_key)
    if cached:
        logger.debug("TCP: token resolved from Redis cache → user_id=%s", cached)
        return cached

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, nt_token_hash, email FROM users "
            "WHERE nt_token_lookup = $1 AND nt_token_hash IS NOT NULL",
            lookup,
        )

    if not rows:
        logger.warning(
            "TCP: no user matches token fingerprint %s… (0 index matches)",
            fingerprint,
        )
        return None

    for row in rows:
        if verify_nt_token(token, row["nt_token_hash"]):
            user_id = str(row["id"])
            await redis_client.set(cache_key, user_id, ex=_TOKEN_CACHE_TTL)
            logger.info("TCP: token verified for %s → user_id=%s", row["email"], user_id)
            return user_id

    # Lookup index matched but bcrypt failed — hash mismatch / rotated token.
    logger.warning(
        "TCP: token fingerprint %s… matched %d index row(s) but bcrypt "
        "verification failed — user should refresh token on the Connect page",
        fingerprint, len(rows),
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
    auth_failures  = 0   # bad tokens seen before a successful resolve
    preauth_lines  = 0   # total lines processed while still unauthenticated

    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break  # Client closed the connection

            buffer += chunk.decode("utf-8", errors="replace")

            # Guard against an endless stream with no newline (memory exhaustion):
            # a legitimate message is far shorter than the buffer cap, so a backlog
            # this large with no line terminator is abusive — drop the connection.
            if len(buffer) > _MAX_BUFFER_BYTES:
                logger.warning(
                    "TCP: buffer overflow from %s (%d bytes, no newline) — closing",
                    addr, len(buffer),
                )
                break

            # Process every complete newline-terminated message in the buffer.
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                if len(line) > _MAX_LINE_BYTES:
                    logger.warning(
                        "TCP: oversized message from %s (%d bytes) — closing",
                        addr, len(line),
                    )
                    return   # finally-block still runs cleanup

                # Cap the number of lines an unauthenticated peer can push. This
                # bounds both a malformed-message flood and a token brute-force.
                if user_id is None:
                    preauth_lines += 1
                    if preauth_lines > _MAX_PREAUTH_MESSAGES:
                        logger.warning(
                            "TCP: %s sent %d messages without authenticating — closing",
                            addr, preauth_lines,
                        )
                        return

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
                        auth_failures += 1
                        logger.warning(
                            "TCP: unknown token from %s: %s*** (%d/%d)",
                            addr, msg.token[:6], auth_failures, _MAX_AUTH_FAILURES,
                        )
                        if auth_failures >= _MAX_AUTH_FAILURES:
                            logger.warning(
                                "TCP: too many bad tokens from %s — closing", addr,
                            )
                            return
                        # Keep reading — the user may reconnect with a correct token.
                        continue
                    await _mark_connected(user_id, db_pool)
                    logger.info("TCP: token validated → user_id=%s", user_id)

                # ── Arm gate ───────────────────────────────────────────────
                # If the user hasn't armed ingestion from the dashboard, refuse
                # the bar outright — never publish it to the stream — so nothing
                # stacks while the strategy is merely connected. The connection
                # stays open; bars resume the moment the user arms.
                if not is_ingestion_armed(user_id):
                    note_bar_refused(user_id)
                    continue

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
                    "timeframe": msg.timeframe,
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
