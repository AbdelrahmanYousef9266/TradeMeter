"""
Redis Streams consumer — reads from 'market:raw', writes bar closes to
TimescaleDB, computes features, runs all 10 ML models, and publishes the
enriched bar payload to Redis pub/sub for the WebSocket broadcaster.

Flow per bar:
  1. Parse stream entry → Tick
  2. Write bar close to TimescaleDB (ticks table)
  3. Compute 10 features via FeatureEngine
  4. If past warmup (features not None):
     a. If prev bar exists: call learn_all() so models learn from last bar's label
     b. Call predict_all() on current features
     c. Store predictions in TimescaleDB
     d. Cache predictions in Redis
     e. Publish enriched bar to pub/sub live:{user_id}
     f. Publish any level-up events as separate messages
  5. Update per-user state for next bar
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
from app.services.ml.pipeline import get_pipeline
from app.core.redis import cache_latest_predictions

logger = logging.getLogger(__name__)

_STREAM_KEY = "market:raw"

# Per-user state: prev_features, prev_predictions, prev_close
# {user_id: {"features": dict, "predictions": dict, "close": float}}
_bar_state: dict[str, dict] = {}


# ── DB write helpers ────────────────────────────────────────────────────────

async def write_tick_to_db(conn: asyncpg.Connection, tick: Tick) -> None:
    await conn.execute(
        """INSERT INTO ticks (time, user_id, symbol, open, high, low, close, volume, bar_type)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        tick.time, tick.user_id, tick.symbol,
        tick.open, tick.high, tick.low, tick.close,
        tick.volume, tick.bar_type,
    )


async def _store_predictions(
    conn: asyncpg.Connection,
    tick: Tick,
    predictions: dict,
) -> None:
    from app.services.ml.models.base import ModelPrediction
    uid = tick.user_id
    for model_name, pred in predictions.items():
        if not isinstance(pred, ModelPrediction):
            continue
        try:
            await conn.execute(
                """INSERT INTO predictions
                       (time, user_id, model_name, signal, confidence,
                        predicted_high, predicted_low, direction_up_prob)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                tick.time, uid, model_name,
                pred.signal, pred.confidence,
                pred.predicted_high, pred.predicted_low,
                pred.direction_up,
            )
        except Exception as exc:
            logger.error("Failed to store prediction for %s: %s", model_name, exc)


# ── Entry processor ─────────────────────────────────────────────────────────

async def _process_entry(
    fields: dict,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    # ── 1. Parse ─────────────────────────────────────────────────────────
    try:
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

    # ── 2. Write bar closes to DB (skip raw ticks) ───────────────────────
    if tick.bar_type == "tick":
        return

    try:
        async with db_pool.acquire() as conn:
            await write_tick_to_db(conn, tick)
    except asyncpg.PostgresError as exc:
        logger.error("Ingestion: DB write failed: %s", exc)
        return

    # ── 3. Compute features ───────────────────────────────────────────────
    try:
        features = get_engine(str(tick.user_id)).update(tick)
    except Exception as exc:
        logger.error("Ingestion: feature computation failed: %s", exc)
        return

    if features is None:
        # Still in 50-bar warmup period — nothing more to do
        return

    # ── 4. ML pipeline ────────────────────────────────────────────────────
    user_id = str(tick.user_id)

    try:
        async with db_pool.acquire() as conn:
            pipeline = await get_pipeline(user_id, conn)

        prev = _bar_state.get(user_id)

        # 4a. Learn from the PREVIOUS bar now that we have the next close as label
        level_up_events = []
        if prev and prev.get("predictions"):
            async with db_pool.acquire() as conn:
                level_up_events = await pipeline.learn_all(
                    features=prev["features"],
                    actual_close=tick.close,
                    prev_close=prev["close"],
                    predictions=prev["predictions"],
                    db_conn=conn,
                    redis_client=redis_client,
                )

        # 4b. Predict for current bar
        predictions = await pipeline.predict_all(features, tick.close)

        # 4c. Store predictions
        async with db_pool.acquire() as conn:
            await _store_predictions(conn, tick, predictions)

        # 4d. Cache predictions in Redis
        pred_cache = {
            name: {
                "signal":         p.signal,
                "confidence":     p.confidence,
                "direction_up":   p.direction_up,
                "direction_down": p.direction_down,
                "predicted_high": p.predicted_high,
                "predicted_low":  p.predicted_low,
            }
            for name, p in predictions.items()
        }
        await cache_latest_predictions(redis_client, user_id, pred_cache)

        # 4e. Publish enriched bar to pub/sub
        levels_dict = {
            name: tracker.to_dict()
            for name, tracker in pipeline.xp_trackers.items()
        }
        ws_payload = json.dumps({
            "type":     "bar",
            "time":     tick.time.isoformat(),
            "bar": {
                "symbol": tick.symbol,
                "open":   tick.open,
                "high":   tick.high,
                "low":    tick.low,
                "close":  tick.close,
                "volume": tick.volume,
                "bar_type": tick.bar_type,
            },
            "features": features,
            "models":   pred_cache,
            "levels":   levels_dict,
        })
        await redis_client.publish(f"live:{user_id}", ws_payload)

        # 4f. Publish level-up events as separate messages
        for event in level_up_events:
            lue_payload = json.dumps({
                "type":       "level_up",
                "model_name": event.model_name,
                "new_level":  event.new_level,
                "new_rank":   event.new_rank,
                "unlocked":   event.unlocked,
            })
            await redis_client.publish(f"live:{user_id}", lue_payload)

        # 5. Save state for next bar's learn call
        _bar_state[user_id] = {
            "features":    features,
            "predictions": predictions,
            "close":       tick.close,
        }

    except Exception as exc:
        logger.error("Ingestion: ML pipeline error for user %s: %s", user_id, exc)


# ── Stream consumer loop ────────────────────────────────────────────────────

async def consume_stream(
    redis_client: aioredis.Redis,
    db_pool: asyncpg.Pool,
) -> None:
    """
    Infinite loop — reads new entries from 'market:raw' with 1-second block.
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
