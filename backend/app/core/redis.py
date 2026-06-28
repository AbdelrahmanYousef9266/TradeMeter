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
    Write a tick to the Redis Stream 'market:raw' and publish to the
    pub/sub channel 'live:{user_id}' for connected WebSocket clients.
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
    }
    await client.xadd("market:raw", entry, maxlen=10_000, approximate=True)

    # Pub/sub publish for WebSocket forwarding — Phase 3 will enrich with predictions.
    payload = {
        "type": "bar" if tick["bar_type"] != "tick" else "tick",
        "time": tick["timestamp"],
        "bar": {
            "symbol":   tick["symbol"],
            "open":     tick["open"],
            "high":     tick["high"],
            "low":      tick["low"],
            "close":    tick["close"],
            "volume":   tick["volume"],
            "bar_type": tick["bar_type"],
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
