import json
import logging
import redis.asyncio as aioredis
from fastapi import Request
from app.core.config import settings

logger = logging.getLogger(__name__)


async def create_redis_client() -> aioredis.Redis:
    """Create and return a connected Redis client."""
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    await client.ping()
    logger.info("Redis client connected")
    return client


async def get_redis(request: Request) -> aioredis.Redis:
    """FastAPI dependency — returns the shared Redis client from app.state."""
    return request.app.state.redis


# ── Stream operations ──────────────────────────────────────────────────────

async def publish_tick(client: aioredis.Redis, user_id: str, tick: dict) -> None:
    """
    Write a message to the Redis Stream 'market:raw' (all messages) and, for
    real-time tick updates only, also publish to the pub/sub channel
    'live:{user_id}' so the dashboard price line stays live between bar closes.

    Bar-close messages are NOT published to pub/sub here — the ingestion
    pipeline reads them from the stream, runs ML, and publishes a single
    enriched payload.  Splitting responsibilities this way prevents the
    duplicate-bar problem caused by two separate pub/sub publishes per close.
    """
    entry = {
        "user_id":   user_id,
        "symbol":    tick["symbol"],
        "timestamp": tick["timestamp"],
        "open":      str(tick["open"]),
        "high":      str(tick["high"]),
        "low":       str(tick["low"]),
        "close":     str(tick["close"]),
        "volume":    str(tick["volume"]),
        "bar_type":  tick["bar_type"],
        "timeframe": tick.get("timeframe", "1min"),
    }
    # Cap the stream so it can't grow without bound, but keep it high enough that
    # a large historical import (up to ~350k bars) can buffer without the oldest
    # UNDELIVERED bars being trimmed away before the consumer drains them. At
    # ~200 bytes/entry this is ~60 MB worst case, and only transiently during an
    # import (the fast bulk path drains it quickly).
    await client.xadd("market:raw", entry, maxlen=300_000, approximate=True)

    # Only forward real-time tick updates directly to pub/sub.
    # Bar-close messages are published by the ingestion pipeline after ML enrichment.
    if tick["bar_type"] == "tick":
        payload = {
            "type": "tick",
            "time": tick["timestamp"],
            "bar": {
                "symbol":   tick["symbol"],
                "open":     tick["open"],
                "high":     tick["high"],
                "low":      tick["low"],
                "close":    tick["close"],
                "volume":   tick["volume"],
                "bar_type": "tick",
            },
        }
        await client.publish(f"live:{user_id}", json.dumps(payload))


# ── Per-user caches ────────────────────────────────────────────────────────

async def cache_latest_tick(client: aioredis.Redis, user_id: str, tick: dict) -> None:
    await client.set(f"latest_tick:{user_id}", json.dumps(tick), ex=300)


async def get_latest_tick(client: aioredis.Redis, user_id: str) -> dict | None:
    raw = await client.get(f"latest_tick:{user_id}")
    return json.loads(raw) if raw else None


async def cache_latest_predictions(
    client: aioredis.Redis, user_id: str, predictions: dict
) -> None:
    await client.set(f"latest_predictions:{user_id}", json.dumps(predictions), ex=300)


async def get_latest_predictions(
    client: aioredis.Redis, user_id: str
) -> dict | None:
    raw = await client.get(f"latest_predictions:{user_id}")
    return json.loads(raw) if raw else None
