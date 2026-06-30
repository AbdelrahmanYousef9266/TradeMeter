"""
Redis Streams consumer — reads from 'market:raw', runs the ML pipeline on bar
closes only, and publishes enriched payloads to Redis pub/sub for the WebSocket
broadcaster.

Message types:
  tick     → publish lightweight price update (pub/sub already done by redis.publish_tick)
  bar close → write to DB, compute features, run ML, publish type:"bar" with predictions

Flow per bar close:
  1. Parse stream entry → Tick
  2. Write bar close to TimescaleDB (non-fatal on failure)
  3. Compute features via FeatureEngine
  4. If in warmup: publish type:"tick" so chart price updates but no ML candle yet
  5. Get or create per-user MLPipeline
  6. Learn from previous bar (if prev predictions exist)
  7. Predict on current bar
  8. Publish type:"bar" with models + levels (BEFORE DB writes)
  9. Cache predictions in Redis
  10. Store predictions in TimescaleDB (non-fatal)
  11. Publish any level-up events
  12. Save state for next bar's learn call
"""

import asyncio
import json
import logging
import uuid as _uuid
from datetime import datetime

import asyncpg
import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from app.models.tick import Tick
from app.services.market_data.features import get_engine
from app.services.ml.pipeline import get_pipeline
from app.core.redis import cache_latest_predictions

logger = logging.getLogger(__name__)

_STREAM_KEY    = "market:raw"
_GROUP_NAME    = "ingestion"     # consumer group — survives consumer restarts
_CONSUMER_NAME = "worker-1"      # stable name so a restart reclaims its pending entries

# Per-user state: prev_features, prev_predictions, prev_close
# {user_id: {"features": dict, "predictions": dict, "close": float}}
_bar_state: dict[str, dict] = {}

# Per-user high-water mark of the last processed bar close time.
# Seeded from the ticks table on first access so it survives restarts.
# {user_id: datetime | None}
_last_bar_time: dict[str, object] = {}


# ── Idempotency / monotonic-order guard ──────────────────────────────────────

async def _accept_bar(user_id: str, tick_time, db_pool: asyncpg.Pool) -> bool:
    """
    Decide whether this bar close should be processed.

    Returns False (skip) when the bar is a duplicate or arrives out of order —
    i.e. its timestamp is not strictly newer than the last one we processed.
    This makes processing idempotent: a consumer-group redelivery (the
    at-least-once side effect of #2) reprocesses the same entry, but the
    durable effects (ticks/predictions rows, model learning) are applied once.

    The high-water mark is seeded once per user from MAX(time) in the ticks
    table, so it holds across a restart even though it lives in memory.
    """
    if user_id not in _last_bar_time:
        watermark = None
        try:
            async with db_pool.acquire() as conn:
                watermark = await conn.fetchval(
                    "SELECT MAX(time) FROM ticks WHERE user_id = $1",
                    _uuid.UUID(user_id),
                )
        except Exception as exc:
            logger.warning("Ingestion: watermark seed failed for %s: %s", user_id, exc)
        _last_bar_time[user_id] = watermark

    last = _last_bar_time[user_id]
    if last is not None and tick_time <= last:
        return False

    _last_bar_time[user_id] = tick_time
    return True


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

    # ── 2. TICK GATE — must be first, nothing ML-related runs past here for ticks ──
    #
    # Ticks are already published to pub/sub by redis.publish_tick before they
    # enter the stream.  The ingestion pipeline has nothing to do with them.
    # Case-insensitive so "Tick" / "TICK" variants from NinjaTrader also match.
    if tick.bar_type.lower() == "tick":
        return

    # ────────────────────────────────────────────────────────────────────────
    # Everything below ONLY runs for bar closes (bar_type != "tick")
    # ────────────────────────────────────────────────────────────────────────

    user_id = str(tick.user_id)

    # ── 2b. IDEMPOTENCY GATE — skip duplicate / out-of-order bars ─────────
    # Must run before any stateful work (feature engine, DB writes, learning)
    # so a redelivered bar can't double-mutate state or insert duplicate rows.
    if not await _accept_bar(user_id, tick.time, db_pool):
        logger.debug(
            "Ingestion: skipping duplicate/stale bar %s for user %s",
            tick.time, user_id,
        )
        return

    # Compact bar dict reused in all outgoing payloads
    _bar = {
        "open":   tick.open,
        "high":   tick.high,
        "low":    tick.low,
        "close":  tick.close,
        "volume": tick.volume,
    }

    # ── 3. Write bar close to DB ──────────────────────────────────────────
    try:
        async with db_pool.acquire() as conn:
            await write_tick_to_db(conn, tick)
    except asyncpg.PostgresError as exc:
        # Non-fatal — ML pipeline and WebSocket publish still run
        logger.error("Ingestion: DB write failed (continuing to ML): %s", exc)

    # ── 4. Compute features ───────────────────────────────────────────────
    engine = get_engine(user_id)
    try:
        features = engine.update(tick)
    except Exception as exc:
        logger.error("Ingestion: feature computation failed: %s", exc)
        return

    if features is None:
        # Still in warmup (< 50 bars). Publish as type "tick" so the frontend
        # updates the live price line but does NOT create a new ML chart candle
        # or update model cards. Include warmup progress so the chart can show
        # a live progress bar instead of "Waiting for bar data".
        try:
            await redis_client.publish(f"live:{user_id}", json.dumps({
                "type": "tick",
                "time": tick.time.isoformat(),
                "bar":  _bar,
                "warmup": {
                    "bars_received": engine.bar_count,
                    "bars_needed":   50,
                    "warming_up":    True,
                },
            }))
        except Exception as exc:
            logger.error("Ingestion: Redis warmup publish failed: %s", exc)
        return

    # ── 5. Get or create per-user ML pipeline ────────────────────────────
    try:
        async with db_pool.acquire() as conn:
            pipeline = await get_pipeline(user_id, conn)
    except Exception as exc:
        logger.error("Ingestion: get_pipeline failed for user %s: %s", user_id, exc)
        return

    # ── 6. Learn from previous bar (Level 3 — trade outcome based) ───────
    prev = _bar_state.get(user_id)
    level_up_events = []
    if prev and prev.get("predictions"):
        try:
            async with db_pool.acquire() as conn:
                level_up_events = await pipeline.learn_all(
                    features=prev["features"],
                    actual_close=tick.close,
                    prev_close=prev["close"],
                    predictions=prev["predictions"],
                    bar_high=tick.high,
                    bar_low=tick.low,
                    bar_time=tick.time,
                    db_conn=conn,
                    redis_client=redis_client,
                )
        except Exception as exc:
            logger.error("Ingestion: learn_all failed for user %s: %s", user_id, exc)

    # ── 7–12. Predict → Publish → Cache → Store → Level-ups ──────────────
    try:
        # 7. Predict on current bar + open simulated trades for non-HOLD signals
        #    (trade opening delegated to predict_all for Phase 6A CC support)
        predictions = await pipeline.predict_all(
            features,
            tick.close,
            next_bar_open = tick.open,
            bar_time      = tick.time,
        )

        pred_cache = {
            name: {
                "signal":         p.signal,
                "confidence":     round(p.confidence, 3),
                "direction_up":   round(p.direction_up, 3),
                "direction_down": round(p.direction_down, 3),
                "predicted_high": round(p.predicted_high, 2),
                "predicted_low":  round(p.predicted_low, 2),
            }
            for name, p in predictions.items()
        }

        levels_dict = {
            name: tracker.to_dict()
            for name, tracker in pipeline.xp_trackers.items()
        }

        session_pnl = pipeline.trade_manager.get_session_pnl()

        # 8. Publish enriched bar BEFORE DB writes — WS must not be blocked by DB.
        await redis_client.publish(f"live:{user_id}", json.dumps({
            "type":     "bar",
            "time":     tick.time.isoformat(),
            "bar":      _bar,
            "features": features,
            "models":   pred_cache,
            "levels":   levels_dict,
            "warmup":   None,   # signals to frontend: past warmup, predictions are live
            "session_pnl": {
                name: {
                    "points":  round(pnl, 2),
                    "dollars": round(pnl * 5.0, 2),
                }
                for name, pnl in session_pnl.items()
            },
        }))

        # 9. Cache latest predictions in Redis
        await cache_latest_predictions(redis_client, user_id, pred_cache)

        # 10. Store predictions in DB (non-fatal)
        try:
            async with db_pool.acquire() as conn:
                await _store_predictions(conn, tick, predictions)
        except Exception as exc:
            logger.error("Ingestion: _store_predictions failed for user %s: %s", user_id, exc)

        # 11. Publish level-up events as separate messages
        for event in level_up_events:
            await redis_client.publish(f"live:{user_id}", json.dumps({
                "type":       "level_up",
                "model_name": event.model_name,
                "new_level":  event.new_level,
                "new_rank":   event.new_rank,
                "unlocked":   event.unlocked,
            }))

        # 12. Save state for next bar's learn call
        _bar_state[user_id] = {
            "features":    features,
            "predictions": predictions,
            "close":       tick.close,
        }

    except Exception as exc:
        logger.error("Ingestion: ML pipeline error for user %s: %s", user_id, exc)


# ── Stream consumer loop (consumer-group based) ──────────────────────────────
#
# Why a consumer group instead of a plain XREAD from '$':
#   A plain XREAD starting at '$' only sees messages that arrive *after* the
#   read begins, so any bar that lands in the stream while the consumer is down
#   (crash, restart, deploy) is silently lost.
#
#   A consumer group tracks a last-delivered-id server-side.  Once the group
#   exists, every message added to the stream is retained for the group until
#   it is explicitly XACK'd — even if no consumer is connected.  On restart the
#   consumer picks up everything that arrived during the gap, giving
#   at-least-once delivery instead of at-most-once-with-loss.


async def _ensure_group(redis_client: aioredis.Redis) -> None:
    """Create the consumer group if it doesn't exist (idempotent)."""
    try:
        await redis_client.xgroup_create(
            _STREAM_KEY, _GROUP_NAME, id="$", mkstream=True
        )
        logger.info("Created consumer group '%s' on stream '%s'", _GROUP_NAME, _STREAM_KEY)
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            logger.info("Consumer group '%s' already exists", _GROUP_NAME)
        else:
            raise


async def _handle_entry(
    entry_id: str,
    fields: dict,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    """Process one stream entry and ACK it (always, to avoid poison-pill redelivery)."""
    try:
        await _process_entry(fields, db_pool, redis_client)
    except Exception as exc:
        logger.error(
            "Ingestion: processing failed for %s (acking to avoid poison pill): %s",
            entry_id, exc,
        )
    finally:
        try:
            await redis_client.xack(_STREAM_KEY, _GROUP_NAME, entry_id)
        except Exception as exc:
            logger.error("Ingestion: xack failed for %s: %s", entry_id, exc)


async def _drain_pending(
    redis_client: aioredis.Redis,
    db_pool: asyncpg.Pool,
) -> None:
    """
    Reprocess entries that were delivered to this consumer but never ACK'd —
    i.e. bars this worker was mid-processing when it last crashed.  Reading
    with id '0' returns this consumer's pending-entries list.
    """
    try:
        result = await redis_client.xreadgroup(
            _GROUP_NAME, _CONSUMER_NAME, {_STREAM_KEY: "0"}, count=1000
        )
    except Exception as exc:
        logger.error("Ingestion: pending recovery read failed: %s", exc)
        return

    recovered = 0
    for _stream_name, entries in result or []:
        for entry_id, fields in entries:
            await _handle_entry(entry_id, fields, db_pool, redis_client)
            recovered += 1

    if recovered:
        logger.info(
            "Ingestion: recovered %d pending entr%s from a previous run",
            recovered, "y" if recovered == 1 else "ies",
        )


async def consume_stream(
    redis_client: aioredis.Redis,
    db_pool: asyncpg.Pool,
) -> None:
    """
    Consume 'market:raw' via a consumer group.

    Startup: ensure the group exists, then drain any pending (crashed-mid-process)
    entries.  Steady state: block-read new messages with '>' and ACK each after
    processing.  Messages that arrived while the consumer was down are delivered
    here because the group retained them.
    """
    logger.info(
        "Ingestion consumer starting on stream '%s' (group=%s, consumer=%s)",
        _STREAM_KEY, _GROUP_NAME, _CONSUMER_NAME,
    )

    try:
        await _ensure_group(redis_client)
    except Exception as exc:
        logger.error("Ingestion: could not create consumer group: %s", exc)

    # Recover anything left in-flight from a prior crash before taking new work.
    await _drain_pending(redis_client, db_pool)

    while True:
        try:
            result = await redis_client.xreadgroup(
                _GROUP_NAME, _CONSUMER_NAME,
                {_STREAM_KEY: ">"},
                count=100,
                block=1000,
            )
            if not result:
                continue

            for _stream_name, entries in result:
                for entry_id, fields in entries:
                    await _handle_entry(entry_id, fields, db_pool, redis_client)

        except asyncio.CancelledError:
            logger.info("Ingestion consumer cancelled")
            break
        except ResponseError as exc:
            # Group was dropped (e.g. Redis restarted/flushed) — recreate and continue.
            if "NOGROUP" in str(exc):
                logger.warning("Ingestion: consumer group missing — recreating")
                try:
                    await _ensure_group(redis_client)
                except Exception as e2:
                    logger.error("Ingestion: group recreate failed: %s", e2)
                await asyncio.sleep(1)
            else:
                logger.error("Ingestion: stream read error: %s", exc)
                await asyncio.sleep(1)
        except Exception as exc:
            logger.error("Ingestion: stream read error: %s", exc)
            await asyncio.sleep(1)
