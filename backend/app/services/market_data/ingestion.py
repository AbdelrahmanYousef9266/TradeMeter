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
import time
import uuid as _uuid
from datetime import datetime

import asyncpg
import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from app.models.tick import Tick
from app.services.market_data.features import get_engine, get_et_time, warm_start_engine
from app.services.ml.pipeline import get_pipeline
from app.core.redis import cache_latest_predictions

logger = logging.getLogger(__name__)

_STREAM_KEY    = "market:raw"
_GROUP_NAME    = "ingestion"     # consumer group — survives consumer restarts
_CONSUMER_NAME = "worker-1"      # stable name so a restart reclaims its pending entries

# Phase 2: every timeframe now runs the full features/learning/prediction path on
# its OWN engine and pipeline (see get_engine/get_pipeline, both keyed by
# (user, timeframe)). There is no longer a single "ML timeframe" gate — 1-min and
# 5-min are independent series. The LSTM is the only model scoped to one timeframe
# (5-min), enforced in the pipeline via model_names_for().

# Per-user state: prev_features, prev_predictions, prev_close
# {user_id: {"features": dict, "predictions": dict, "close": float}}
_bar_state: dict[str, dict] = {}

# Per-user high-water mark of the last processed LIVE bar close time.
# Seeded from the ticks table (live rows only) on first access so it survives
# restarts. {user_id: datetime | None}
_last_bar_time: dict[str, object] = {}

# Fast-import weight-save throttle: pickling all models is the batch's dominant
# cost, so only persist learned weights every N imported bars (plus a final save
# when the queue drains). Levels persist every batch (cheap). {user_id: bars}
_hist_save_accum: dict[str, int] = {}
_HIST_STATE_SAVE_EVERY = 5000


# ── System MODE (per-user): LIVE or OFFLINE ──────────────────────────────────
#
# The system is in exactly ONE mode at a time, per user:
#
#   LIVE (default)  — trades forward real-time data. Live bar closes flow into the
#                     'live' context pipeline/engine; historical ("hist") bars are
#                     REFUSED at the gate.
#   OFFLINE         — trains on history. "hist" bars flow into the SEPARATE
#                     'offline' context (a copy of the live models that learns
#                     independently, tagged is_training=true, watermark bypassed);
#                     live forward bars are REFUSED at the gate.
#
# This REPLACES the old "training mode is a flag on the live path" design: OFFLINE
# mode is what training mode used to do (watermark bypass + is_training tagging),
# but it now routes to its own models/feature-engine so historical learning can
# never contaminate live. The offline→live merge is an explicit promotion only.
#
# In-memory, per-user, mirroring the other registries. The training counters below
# are reused as the OFFLINE run's progress counters.
MODE_LIVE    = "live"
MODE_OFFLINE = "offline"

_system_mode:        dict[str, str] = {}   # user_id -> "live" | "offline"
_training_bar_count: dict[str, int] = {}   # offline run: bars ingested this run
_training_sessions:  dict[str, set] = {}   # offline run: distinct ET session dates


# All access to the per-user registries goes through helpers that canonicalize the
# key with str(user_id) as their first act. This is the single source of truth for
# the key form: the API path passes str(user.id) and the ingestion path passes
# str(tick.user_id) — both already canonical lowercase UUID strings — but
# normalizing *inside* the accessor makes it impossible for any caller to set a
# value under one key form and read it under another (str vs uuid.UUID).
def _key(user_id) -> str:
    return str(user_id)


def get_mode(user_id) -> str:
    """Current system mode for the user. Default: LIVE."""
    return _system_mode.get(_key(user_id), MODE_LIVE)


def set_mode(user_id, mode: str) -> dict:
    """
    Set the system mode. Switching INTO offline resets this-run offline counters.
    Callers (the /mode routes) are responsible for the queue-drain guard before
    calling this — this function only flips the in-memory flag.
    """
    if mode not in (MODE_LIVE, MODE_OFFLINE):
        raise ValueError(f"invalid mode {mode!r} (expected {MODE_LIVE!r} or {MODE_OFFLINE!r})")
    uid = _key(user_id)
    _system_mode[uid] = mode
    if mode == MODE_OFFLINE:
        _training_bar_count[uid] = 0
        _training_sessions[uid]  = set()
    logger.info("System mode → %s for user %s", mode.upper(), uid)
    return mode_status(uid)


def mode_status(user_id) -> dict:
    uid = _key(user_id)
    return {
        "mode":              get_mode(uid),
        "bars_ingested":     _training_bar_count.get(uid, 0),
        "sessions_ingested": len(_training_sessions.get(uid, ())),
    }


def context_for_mode(user_id) -> str:
    """The model/engine context the current mode routes bars into."""
    return "offline" if get_mode(user_id) == MODE_OFFLINE else "live"


# ── Backward-compatible training aliases ─────────────────────────────────────
# OFFLINE mode == the old "training mode". These keep the ingestion fast-path
# routing, is_training tagging, and the /training/* endpoints working while the
# mode switch is the real source of truth.
def is_training_mode(user_id) -> bool:
    """True iff the user is in OFFLINE mode (the old training-mode semantics)."""
    return get_mode(user_id) == MODE_OFFLINE


def start_training(user_id) -> dict:
    """Alias: enter OFFLINE mode (reset this-run counters)."""
    return set_mode(user_id, MODE_OFFLINE)


def stop_training(user_id) -> dict:
    """Alias: return to LIVE mode."""
    return set_mode(user_id, MODE_LIVE)


def training_status(user_id) -> dict:
    """Legacy shape: {training, bars_ingested, sessions_ingested}."""
    st = mode_status(user_id)
    return {
        "training":          st["mode"] == MODE_OFFLINE,
        "bars_ingested":     st["bars_ingested"],
        "sessions_ingested": st["sessions_ingested"],
    }


def _note_training_bar(user_id, bar_time) -> None:
    """Advance the OFFLINE run's counters for one imported bar (key-normalized)."""
    uid = _key(user_id)
    _training_bar_count[uid] = _training_bar_count.get(uid, 0) + 1
    try:
        _training_sessions.setdefault(uid, set()).add(get_et_time(bar_time).date())
    except Exception:
        pass


# ── Mode-enforcement gate (per-user) ─────────────────────────────────────────
#
# Exactly one KIND of bar is accepted per mode: LIVE accepts live bar closes and
# refuses "hist"; OFFLINE accepts "hist" and refuses live. A refused bar never
# enters any pipeline. Refusals are logged at most once per user per interval so a
# wrong-mode strategy blasting bars can't flood the log.
_mode_reject_at: dict[str, float] = {}
_MODE_REJECT_INTERVAL = 30.0   # seconds between refusal logs per user


def _is_hist_bar(bar_type: str) -> bool:
    return (bar_type or "").lower() == "hist"


def bar_allowed_in_mode(user_id, bar_type: str) -> bool:
    """
    True if a bar of this type may enter under the user's current mode.
    LIVE → live (non-hist) bars only; OFFLINE → hist bars only. Ticks are handled
    upstream and are not mode-gated here.
    """
    hist = _is_hist_bar(bar_type)
    return not hist if get_mode(user_id) == MODE_LIVE else hist


def _warn_mode_reject(user_id: str, bar_type: str) -> None:
    now  = time.monotonic()
    last = _mode_reject_at.get(user_id, 0.0)
    if now - last >= _MODE_REJECT_INTERVAL:
        _mode_reject_at[user_id] = now
        mode = get_mode(user_id)
        kind = "historical" if _is_hist_bar(bar_type) else "live"
        logger.info(
            "Ingestion: %s bar refused for user %s — system is in %s mode "
            "(switch modes from the dashboard to accept it)",
            kind, user_id, mode.upper(),
        )


# ── Ingestion arm gate (per-user) ────────────────────────────────────────────
#
# Enabling the NinjaTrader strategy immediately streams bars over TCP, so without
# a gate they pour into 'market:raw' and stack the queue the instant the strategy
# connects. The arm gate lets the user decide WHEN bars enter the pipeline: while
# DISARMED (the default at startup) every incoming bar is refused at the TCP
# intake — never queued, never stored — so the strategy can stay connected with
# nothing accumulating. Arming from the dashboard opens the gate.
#
# Independent of training mode: arming controls whether bars enter the pipeline
# at all; training mode controls whether accepted historical/out-of-order bars
# bypass the live watermark. Uses the same canonical str(user_id) key form as the
# training registries via _key().
_ingestion_armed: dict[str, bool] = {}

# Rate-limited "bar refused" logging so a connected-but-disarmed strategy blasting
# bars can't flood the log. {user_id: monotonic ts of last log}
_disarm_log_at: dict[str, float] = {}
_DISARM_LOG_INTERVAL = 30.0   # seconds between refusal logs per user


def is_ingestion_armed(user_id) -> bool:
    """True if the user has armed ingestion. Default: disarmed (bars refused)."""
    return _ingestion_armed.get(_key(user_id), False)


def arm_ingestion(user_id) -> dict:
    """Open the gate — incoming strategy bars start flowing into the pipeline."""
    uid = _key(user_id)
    _ingestion_armed[uid] = True
    logger.info("Ingestion ARMED for user %s", uid)
    return ingestion_armed_status(uid)


def disarm_ingestion(user_id) -> dict:
    """Close the gate — incoming strategy bars are refused (not queued/stored)."""
    uid = _key(user_id)
    _ingestion_armed[uid] = False
    logger.info("Ingestion DISARMED for user %s", uid)
    return ingestion_armed_status(uid)


def ingestion_armed_status(user_id) -> dict:
    uid = _key(user_id)
    return {"armed": _ingestion_armed.get(uid, False)}


def note_bar_refused(user_id) -> None:
    """Rate-limited debug log for a bar dropped because ingestion is disarmed."""
    uid = _key(user_id)
    now  = time.monotonic()
    last = _disarm_log_at.get(uid, 0.0)
    if now - last >= _DISARM_LOG_INTERVAL:
        _disarm_log_at[uid] = now
        logger.debug(
            "Ingestion disarmed for user %s — bar refused (arm from the dashboard "
            "to begin receiving bars)", uid,
        )


# ── Historical bulk-import guard ─────────────────────────────────────────────
#
# The NinjaTrader strategy can blast weeks of chart history in seconds using
# bar_type "hist". Those bars must ONLY be ingested while training mode is on —
# otherwise a stray SendHistorical=true would pour historical bars into the live
# dataset and fight the monotonic watermark. When rejected we log at most once
# per user per interval so a 23k-bar blast can't flood the log.
_hist_reject_warn_at: dict[str, float] = {}
_HIST_REJECT_WARN_INTERVAL = 30.0   # seconds between warnings per user


def _warn_hist_rejected(user_id: str) -> None:
    now  = time.monotonic()
    last = _hist_reject_warn_at.get(user_id, 0.0)
    if now - last >= _HIST_REJECT_WARN_INTERVAL:
        _hist_reject_warn_at[user_id] = now
        logger.warning(
            "Ingestion: historical bar received for user %s but training mode is "
            "off — enable Training Mode before bulk-importing history (bars ignored)",
            user_id,
        )


# ── Queue depth + flush ──────────────────────────────────────────────────────
#
# The 'market:raw' stream and its consumer group are SHARED across users (this is
# a 1-2 user deployment, so that is acceptable). queue_pending reports the whole
# stream's depth; flush_queue discards the whole backlog. Per-user in-memory
# state (the deferred-trade buffer) is cleared only for the requesting user.

async def get_queue_pending(redis_client: aioredis.Redis) -> int:
    """Approximate number of bars still queued in the ingestion stream."""
    try:
        return int(await redis_client.xlen(_STREAM_KEY))
    except Exception:
        return 0


async def _clear_group_pending(redis_client: aioredis.Redis) -> None:
    """
    Best-effort: ACK any entries still in the consumer group's pending list so a
    just-trimmed backlog isn't re-read. Version-tolerant across redis-py releases.
    """
    try:
        pend = await redis_client.xpending(_STREAM_KEY, _GROUP_NAME)
    except Exception:
        return
    total = 0
    if isinstance(pend, dict):
        total = pend.get("pending", 0) or 0
    elif isinstance(pend, (list, tuple)) and pend:
        total = pend[0] or 0
    if not total:
        return
    try:
        detail = await redis_client.xpending_range(
            _STREAM_KEY, _GROUP_NAME, min="-", max="+", count=10000
        )
        for item in detail or []:
            entry_id = item["message_id"] if isinstance(item, dict) else item[0]
            try:
                await redis_client.xack(_STREAM_KEY, _GROUP_NAME, entry_id)
            except Exception:
                pass
    except Exception:
        pass


async def flush_queue(user_id: str, redis_client: aioredis.Redis) -> int:
    """
    Discard everything queued in 'market:raw' and clear the user's deferred
    state so no orphaned trade fires from a half-processed import.

    Returns the number of stream entries dropped. Anything discarded is
    re-importable via the strategy's gap-fill, so this is safe to call.
    """
    dropped = await get_queue_pending(redis_client)
    try:
        await redis_client.xtrim(_STREAM_KEY, maxlen=0, approximate=False)
    except Exception as exc:
        logger.warning("flush_queue: XTRIM failed: %s", exc)
    await _clear_group_pending(redis_client)

    # Drop the per-(user, timeframe) deferred learning state and any buffered
    # (not-yet-filled) trade signals so nothing fires against discarded bars.
    # State is keyed by (user_id, timeframe), so clear every timeframe for the user.
    uid = str(user_id)
    for k in [k for k in _bar_state if k[0] == uid]:
        _bar_state.pop(k, None)
    try:
        from app.services.ml.pipeline import _pipelines
        for pkey, pl in _pipelines.items():
            if pkey[0] == uid and pl is not None:
                pl._pending_champion = []
                pl._pending_challenger = []
    except Exception:
        pass

    logger.info("flush_queue: dropped %d queued entr%s for user %s",
                dropped, "y" if dropped == 1 else "ies", uid)
    return dropped


# ── Idempotency / monotonic-order guard (per timeframe) ──────────────────────

def _wm_key(user_id: str, timeframe: str, context: str = "live") -> tuple[str, str, str]:
    """Watermark key — one high-water mark per (user, timeframe, context) series.

    Only the live context enforces a monotonic watermark (offline replays history
    out of order by design), but the key carries context so the two never share a
    mark."""
    return (user_id, timeframe, context)


async def _accept_bar(user_id: str, timeframe: str, tick_time, db_pool: asyncpg.Pool,
                      context: str = "live") -> bool:
    """
    Decide whether this LIVE bar close should be processed. The high-water mark is
    per (user_id, timeframe, context): a 1-min and a 5-min series each have their
    own watermark, so a 5-min bar never dedups against a 1-min bar at the same
    time.

    Returns False (skip) when the bar is a duplicate or arrives out of order for
    ITS series — i.e. its timestamp is not strictly newer than the last one we
    processed. Seeded once from MAX(time) for the (user, timeframe) live rows so
    it holds across a restart.
    """
    key = _wm_key(user_id, timeframe, context)
    if key not in _last_bar_time:
        watermark = None
        try:
            async with db_pool.acquire() as conn:
                watermark = await conn.fetchval(
                    "SELECT MAX(time) FROM ticks "
                    "WHERE user_id = $1 AND timeframe = $2 AND is_training = false",
                    _uuid.UUID(user_id), timeframe,
                )
        except Exception as exc:
            logger.warning("Ingestion: watermark seed failed for %s/%s: %s", user_id, timeframe, exc)
        _last_bar_time[key] = watermark

    last = _last_bar_time[key]
    if last is not None and tick_time <= last:
        return False

    _last_bar_time[key] = tick_time
    return True


# ── Parsing ─────────────────────────────────────────────────────────────────

def _parse_tick(fields: dict) -> Tick:
    """Build a Tick from a raw Redis-stream entry. Raises KeyError/ValueError."""
    return Tick(
        time=datetime.fromisoformat(fields["timestamp"]),
        user_id=_uuid.UUID(fields["user_id"]),
        symbol=fields["symbol"],
        open=float(fields["open"]),
        high=float(fields["high"]),
        low=float(fields["low"]),
        close=float(fields["close"]),
        volume=int(fields["volume"]),
        bar_type=fields["bar_type"],
        timeframe=fields.get("timeframe", "1min"),
    )


# ── DB write helpers ────────────────────────────────────────────────────────

_TICK_COLUMNS = ["time", "user_id", "symbol", "open", "high", "low",
                 "close", "volume", "bar_type", "is_training", "timeframe"]


async def write_tick_to_db(
    conn: asyncpg.Connection, tick: Tick, is_training: bool = False
) -> None:
    await conn.execute(
        """INSERT INTO ticks (time, user_id, symbol, open, high, low, close, volume, bar_type, is_training, timeframe)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
        tick.time, tick.user_id, tick.symbol,
        tick.open, tick.high, tick.low, tick.close,
        tick.volume, tick.bar_type, is_training, tick.timeframe,
    )


async def _copy_ticks_to_db(
    db_pool: asyncpg.Pool, ticks: list[Tick], is_training: bool
) -> int:
    """
    Bulk-insert many bars in ONE round trip via COPY (asyncpg
    copy_records_to_table) instead of one INSERT per bar. This is the single
    biggest speedup for large historical imports — ~100k rows land in a couple
    of batched COPYs instead of 100k separate INSERTs. Returns rows written.

    Each row carries its own timeframe, so a mixed 1-min/5-min batch stores each
    bar in its own series (no collision even at a shared timestamp).
    """
    if not ticks:
        return 0
    records = [
        (t.time, t.user_id, t.symbol, t.open, t.high, t.low,
         t.close, t.volume, t.bar_type, is_training, t.timeframe)
        for t in ticks
    ]
    async with db_pool.acquire() as conn:
        await conn.copy_records_to_table("ticks", records=records, columns=_TICK_COLUMNS)
    return len(records)


async def _store_predictions(
    conn: asyncpg.Connection,
    tick: Tick,
    predictions: dict,
    is_training: bool = False,
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
                        predicted_high, predicted_low, direction_up_prob, is_training, timeframe)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                tick.time, uid, model_name,
                pred.signal, pred.confidence,
                pred.predicted_high, pred.predicted_low,
                pred.direction_up, is_training, tick.timeframe,
            )
        except Exception as exc:
            logger.error("Failed to store prediction for %s: %s", model_name, exc)


# ── Warm-start ───────────────────────────────────────────────────────────────
#
# A FeatureEngine keeps only in-memory rolling indicator state, so a fresh engine
# (first bar after a backend restart) needs 50 bars before it produces features —
# meaning ~50 live bars of blindness (hours on a 5-min series). Warm-start replays
# the most recent STORED bars for the (user, timeframe, context) through the
# engine so it exits warmup on the very first real bar. This is FEATURES ONLY — no
# model is touched, nothing is learned; it only primes EMA/RSI/ATR/VWAP/MACD.
_warmed_engines: set = set()
_WARMUP_LOAD_BARS = 60   # a little over the 50-bar warmup so the next bar is live


async def _maybe_warm_start(user_id, timeframe, context, db_pool, before_time=None) -> None:
    """Prime a fresh engine once from stored bars (see module note). Idempotent
    per (user, timeframe, context); a no-op if the engine already has state."""
    key = (str(user_id), timeframe, context)
    if key in _warmed_engines:
        return
    _warmed_engines.add(key)   # mark first so a failure never re-attempts every bar

    engine = get_engine(user_id, timeframe, context)
    if engine.bar_count > 0:
        return   # already primed (not a fresh engine)

    is_training = context == "offline"
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT time, symbol, open, high, low, close, volume, bar_type, timeframe
                   FROM ticks
                   WHERE user_id = $1 AND timeframe = $2 AND is_training = $3
                     AND bar_type <> 'tick' AND ($4::timestamptz IS NULL OR time < $4)
                   ORDER BY time DESC
                   LIMIT $5""",
                _uuid.UUID(str(user_id)), timeframe, is_training, before_time, _WARMUP_LOAD_BARS,
            )
    except Exception as exc:
        logger.warning("Ingestion: warm-start load failed for %s/%s/%s: %s", user_id, timeframe, context, exc)
        return

    bars = [
        Tick(
            time=r["time"], user_id=_uuid.UUID(str(user_id)), symbol=r["symbol"],
            open=r["open"], high=r["high"], low=r["low"], close=r["close"],
            volume=r["volume"], bar_type=r["bar_type"], timeframe=r["timeframe"],
        )
        for r in reversed(rows)   # oldest → newest
    ]
    fed = warm_start_engine(engine, bars)
    if fed:
        logger.info(
            "Ingestion: warm-started %s/%s/%s engine with %d stored bars (features only)",
            user_id, timeframe, context, fed,
        )


# ── Entry processor ─────────────────────────────────────────────────────────

async def _process_entry(
    fields: dict,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    # ── 1. Parse ─────────────────────────────────────────────────────────
    try:
        tick = _parse_tick(fields)
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

    # ── 2a. MODE GATE — exactly one KIND of bar is accepted per mode ──────
    # LIVE accepts live bar closes and refuses "hist"; OFFLINE accepts "hist" and
    # refuses live. A wrong-kind bar is refused here and never enters any pipeline
    # or storage. (OFFLINE "hist" bars normally take the fast bulk path in
    # _route_entries and never reach here; this gate is the authoritative backstop
    # and the place a LIVE-mode hist bar or an OFFLINE-mode live bar is dropped.)
    if not bar_allowed_in_mode(user_id, tick.bar_type):
        _warn_mode_reject(user_id, tick.bar_type)
        return

    training = is_training_mode(user_id)           # True ⇒ OFFLINE mode
    context  = context_for_mode(user_id)           # "offline" | "live"

    # ── 2b. IDEMPOTENCY GATE — skip duplicate / out-of-order bars ─────────
    # Must run before any stateful work (feature engine, DB writes, learning)
    # so a redelivered bar can't double-mutate state or insert duplicate rows.
    #
    # OFFLINE mode bypasses this entirely: replaying history means bars are
    # deliberately in the past / out of order. We also never call _accept_bar
    # here (it advances the live watermark) so live forward data resumes cleanly
    # once the user returns to LIVE mode.
    if not training:
        if not await _accept_bar(user_id, tick.timeframe, tick.time, db_pool, context):
            logger.debug(
                "Ingestion: skipping duplicate/stale %s bar %s for user %s",
                tick.timeframe, tick.time, user_id,
            )
            return
    else:
        _note_training_bar(user_id, tick.time)

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
            await write_tick_to_db(conn, tick, is_training=training)
    except asyncpg.PostgresError as exc:
        # Non-fatal — ML pipeline and WebSocket publish still run
        logger.error("Ingestion: DB write failed (continuing to ML): %s", exc)

    # ── 3b. FEATURES/ML PER (TIMEFRAME, CONTEXT) ──────────────────────────
    # Every (timeframe, context) runs the full features/learning/prediction path
    # on its OWN engine and pipeline. 1-min vs 5-min and live vs offline are all
    # fully independent — separate rolling indicator state, separate models. lstm
    # runs on the 5-min pipeline only. In practice this per-bar path handles LIVE
    # bars (offline bars take the fast bulk path), so context is "live" here.
    tf = tick.timeframe
    bs_key = (user_id, tf, context)

    # Warm-start the fresh engine from recent stored bars so it exits the 50-bar
    # warmup immediately after a restart (features only — no model learning).
    await _maybe_warm_start(user_id, tf, context, db_pool, before_time=tick.time)

    # ── 4. Compute features ───────────────────────────────────────────────
    engine = get_engine(user_id, tf, context)
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
                "timeframe": tf,
                "context": context,
                "training": training,
                "warmup": {
                    "bars_received": engine.bar_count,
                    "bars_needed":   50,
                    "warming_up":    True,
                },
            }))
        except Exception as exc:
            logger.error("Ingestion: Redis warmup publish failed: %s", exc)
        return

    # ── 5. Get or create the per-(user, timeframe, context) ML pipeline ──
    try:
        async with db_pool.acquire() as conn:
            pipeline = await get_pipeline(user_id, conn, tf, context)
    except Exception as exc:
        logger.error("Ingestion: get_pipeline failed for user %s/%s/%s: %s", user_id, tf, context, exc)
        return

    # ── 6. Learn from previous bar (Level 3 — trade outcome based) ───────
    prev = _bar_state.get(bs_key)
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
            current_bar_open = tick.open,
            bar_time         = tick.time,
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

        # Enrich per-model P&L with win/loss and open-trade counts for the cards.
        # Points and win/loss counts are today's session, read from incremental
        # counters (never a rescan of the trade history) so they stay in sync and
        # cost O(1) per model regardless of how many trades have closed.
        tm = pipeline.trade_manager
        pnl_detail = {}
        for name in pipeline.xp_trackers.keys():
            stats      = tm.get_session_stats(name)
            open_count = len(tm.open_trades.get(name, []))
            pnl_detail[name] = {
                "points":  round(stats["points"], 2),
                "dollars": round(stats["points"] * 5.0, 2),
                "wins":    stats["wins"],
                "losses":  stats["losses"],
                "open":    open_count,
            }

        # 8. Publish enriched bar BEFORE DB writes — WS must not be blocked by DB.
        await redis_client.publish(f"live:{user_id}", json.dumps({
            "type":        "bar",
            "time":        tick.time.isoformat(),
            "bar":         _bar,
            "timeframe":   tf,          # which series this bar/models belong to
            "context":     context,     # "live" | "offline" — which model set
            "features":    features,
            "models":      pred_cache,
            "levels":      levels_dict,
            "warmup":      None,   # signals to frontend: past warmup, predictions are live
            "session_pnl": pnl_detail,
            "training":    training,   # historical replay vs live forward data
        }))

        # 9. Cache latest predictions in Redis
        await cache_latest_predictions(redis_client, user_id, pred_cache, timeframe=tf)

        # 10. Store predictions in DB (non-fatal)
        try:
            async with db_pool.acquire() as conn:
                await _store_predictions(conn, tick, predictions, is_training=training)
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

        # 12. Save state for next bar's learn call (per timeframe)
        _bar_state[bs_key] = {
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


async def _ack(redis_client: aioredis.Redis, entry_id: str) -> None:
    try:
        await redis_client.xack(_STREAM_KEY, _GROUP_NAME, entry_id)
    except Exception as exc:
        logger.error("Ingestion: xack failed for %s: %s", entry_id, exc)


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
        await _ack(redis_client, entry_id)


# ── Fast bulk-import path (historical bars in training mode) ─────────────────
#
# Historical "hist" bars during training mode are the ONLY case that arrives in
# huge bursts (a year ≈ 98k bars). The per-bar live path (one INSERT for the
# bar + ~10 prediction INSERTs + a per-bar level upsert + a full WebSocket bar
# payload) makes that take hours. This batched path instead:
#   • COPYs all the bars in one round trip,
#   • runs the SAME in-memory ML learning (River learn_one, XP, simulated trades)
#     but WITHOUT per-bar prediction storage or a per-bar WS broadcast,
#   • persists levels + weights once per batch, and
#   • emits ONE throttled "training_progress" event per batch for the UI.

async def _process_hist_batch(
    batch: list,                      # list[(entry_id, Tick)] — all hist + training-on
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    # Group by (user, timeframe): each timeframe learns on its OWN engine and
    # pipeline (Phase 2), so a mixed 1-min/5-min batch trains both independent
    # series in the same pass.
    by_series: dict[tuple[str, str], list] = {}
    for _entry_id, tick in batch:
        by_series.setdefault((str(tick.user_id), tick.timeframe), []).append(tick)

    # 1. Bulk-store EVERY bar of EVERY series in one COPY — each row carries its
    #    own timeframe, so the series stay isolated even at a shared timestamp.
    all_ticks = [t for _e, t in batch]
    try:
        await _copy_ticks_to_db(db_pool, all_ticks, is_training=True)
    except Exception as exc:
        logger.error("Ingestion(fast): COPY failed (%d bars): %s", len(all_ticks), exc)

    # 2. Advance the training run counters for every imported bar (per user).
    for _e, tick in batch:
        _note_training_bar(str(tick.user_id), tick.time)

    pending = await get_queue_pending(redis_client)
    users_seen: set[str] = set()

    # Bulk-imported "hist" bars are OFFLINE training data by definition — they
    # learn on the SEPARATE offline engine + pipeline (a copy of live that never
    # mutates live), tagged is_training=true above.
    context = "offline"
    for (user_id, tf), ticks in by_series.items():
        users_seen.add(user_id)

        # 3. In-memory learning on this timeframe's OFFLINE engine + pipeline.
        engine = get_engine(user_id, tf, context)
        try:
            async with db_pool.acquire() as conn:
                pipeline = await get_pipeline(user_id, conn, tf, context)
        except Exception as exc:
            logger.error("Ingestion(fast): get_pipeline failed for %s/%s/%s: %s", user_id, tf, context, exc)
            continue

        bs_key = (user_id, tf, context)
        for tick in ticks:
            try:
                features = engine.update(tick)
            except Exception:
                continue
            if features is None:
                continue   # warmup
            prev = _bar_state.get(bs_key)
            if prev and prev.get("predictions"):
                try:
                    await pipeline.learn_all(
                        features=prev["features"], actual_close=tick.close,
                        prev_close=prev["close"], predictions=prev["predictions"],
                        bar_high=tick.high, bar_low=tick.low, bar_time=tick.time,
                        db_conn=None, redis_client=redis_client, fast_mode=True,
                    )
                except Exception as exc:
                    logger.error("Ingestion(fast): learn_all failed for %s/%s: %s", user_id, tf, exc)
            try:
                predictions = await pipeline.predict_all(
                    features, tick.close, current_bar_open=tick.open, bar_time=tick.time,
                )
                _bar_state[bs_key] = {
                    "features": features, "predictions": predictions, "close": tick.close,
                }
            except Exception as exc:
                logger.error("Ingestion(fast): predict_all failed for %s/%s: %s", user_id, tf, exc)

        # 4. Persist the level ladder every batch (cheap). Weights are pickled +
        #    written far less often (pickling all models is the batch's main cost)
        #    — every _HIST_STATE_SAVE_EVERY bars, plus a final save when the queue
        #    drains so the last partial chunk isn't lost. Throttle per (user, tf).
        try:
            async with db_pool.acquire() as conn:
                await pipeline._save_levels(conn)
        except Exception as exc:
            logger.warning("Ingestion(fast): level persist failed for %s/%s: %s", user_id, tf, exc)

        _hist_save_accum[bs_key] = _hist_save_accum.get(bs_key, 0) + len(ticks)
        if _hist_save_accum[bs_key] >= _HIST_STATE_SAVE_EVERY or pending == 0:
            try:
                async with db_pool.acquire() as conn:
                    await pipeline.save_state(conn)
                _hist_save_accum[bs_key] = 0
            except Exception as exc:
                logger.warning("Ingestion(fast): weight persist failed for %s/%s: %s", user_id, tf, exc)

    # 5. One throttled progress event per user (replaces the per-bar WS broadcast).
    for user_id in users_seen:
        await _publish_training_progress(user_id, redis_client, pending)


async def _publish_training_progress(user_id, redis_client, pending=None) -> None:
    """One throttled progress event per batch (not one WS bar per bar)."""
    try:
        if pending is None:
            pending = await get_queue_pending(redis_client)
        await redis_client.publish(f"live:{user_id}", json.dumps({
            "type":          "training_progress",
            "processed":     _training_bar_count.get(user_id, 0),
            "queue_pending": max(0, pending),   # never emit a negative depth
        }))
    except Exception:
        pass


async def _route_entries(
    entries: list,
    db_pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    """
    Split a delivered batch: hist bars whose user is in training mode go to the
    fast COPY+learn path; everything else takes the normal per-entry path.
    """
    fast_batch: list = []
    for entry_id, fields in entries:
        bar_type = (fields.get("bar_type") or "").lower()
        uid      = fields.get("user_id")
        if bar_type == "hist" and uid and is_training_mode(uid):
            try:
                tick = _parse_tick(fields)
            except (KeyError, ValueError) as exc:
                logger.warning("Ingestion: bad hist entry: %s | %s", exc, fields)
                await _ack(redis_client, entry_id)
                continue
            fast_batch.append((entry_id, tick))
        else:
            await _handle_entry(entry_id, fields, db_pool, redis_client)

    if fast_batch:
        try:
            await _process_hist_batch(fast_batch, db_pool, redis_client)
        except Exception as exc:
            logger.error("Ingestion: fast batch failed (%d bars): %s", len(fast_batch), exc)
        finally:
            for entry_id, _tick in fast_batch:
                await _ack(redis_client, entry_id)


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
                # Route the whole batch at once so consecutive historical bars can
                # be COPY'd + learned together (the fast bulk-import path).
                await _route_entries(entries, db_pool, redis_client)

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
