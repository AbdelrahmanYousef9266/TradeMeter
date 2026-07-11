"""
Model management endpoints.

All endpoints are scoped to the authenticated user.  The ML pipeline for the
user is fetched lazily — if no bars have arrived yet, model-state responses
reflect fresh defaults (level 1, xp 0).
"""

import logging
import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.core.redis import get_latest_predictions, get_redis
from app.db.database import get_db
from app.models.user import User
from app.services.ml.pipeline import (
    get_pipeline, ALL_MODEL_NAMES, ONLINE_MODEL_NAMES, model_names_for,
    LSTM_TIMEFRAME, _pipelines,
)

# The timeframes the models run on. 5-min is the primary trading timeframe (and
# carries lstm); 1-min is context (9 online models, no lstm). Combined APIs return
# both, tagged; per-model APIs default to the primary (5-min).
MODEL_TIMEFRAMES = ["5min", "1min"]
PRIMARY_TIMEFRAME = "5min"
# The dashboard shows LIVE models by default; pass context=offline to inspect the
# offline (history-trained) copy while a training run is in progress.
VALID_CONTEXTS = ("live", "offline")
DEFAULT_CONTEXT = "live"
from app.services.ml.xp import (
    get_unlocked_settings,
    level_to_rank,
    xp_for_level,
    XPTracker,
    LevelUpEvent,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Settings that each rank unlocks — used for lock-gate validation
_RANK_LOCKED_SETTINGS = {
    "Confidence threshold": "Apprentice",
    "Signal mode presets":  "Pro",
    "Blend weight boost":   "Elite",
    "Aggressive settings":  "Expert",
}

_RANK_ORDER = ["Rookie", "Apprentice", "Pro", "Elite", "Expert", "Master"]

# Per-model defaults — returned when the in-memory pipeline doesn't exist yet
_DEFAULT_SETTINGS: dict[str, dict] = {
    "scalper":        {"min_confidence": 0.52, "max_signals_per_session": 40, "signal_mode": "aggressive"},
    "momentum":       {"min_confidence": 0.62, "max_signals_per_session": 20, "signal_mode": "balanced"},
    "mean_reversion": {"min_confidence": 0.60, "max_signals_per_session": 15, "signal_mode": "balanced",
                       "rsi_overbought": 70, "rsi_oversold": 30},
    "breakout":       {"min_confidence": 0.63, "max_signals_per_session": 12, "signal_mode": "balanced",
                       "volume_spike_threshold": 1.8},
    "conservative":   {"min_confidence": 0.75, "max_signals_per_session": 8,  "signal_mode": "conservative"},
    "aggressive":     {"min_confidence": 0.51, "max_signals_per_session": 50, "signal_mode": "aggressive"},
    "volume":         {"min_confidence": 0.60, "max_signals_per_session": 20, "signal_mode": "balanced",
                       "volume_spike_threshold": 1.8, "delta_imbalance_cutoff": 0.60},
    "contrarian":     {"min_confidence": 0.58, "max_signals_per_session": 15, "signal_mode": "balanced"},
    "personal":       {"min_confidence": 0.60, "max_signals_per_session": 20, "auto_blend": True, "user_weight": 0.25},
}


def _rank_gte(a: str, b: str) -> bool:
    """Returns True if rank `a` is at or above rank `b`."""
    return _RANK_ORDER.index(a) >= _RANK_ORDER.index(b)


# ── List all models ──────────────────────────────────────────────────────────

@router.get("")
async def list_models(
    context: str = DEFAULT_CONTEXT,
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
    conn=Depends(get_db),
) -> list[dict]:
    """
    All 20 models (both timeframes) with level info (from DB) + latest prediction
    signal (from Redis). Each entry is tagged with its `timeframe` and carries a
    composite `id` ("momentum:5min") so the same model_name on two timeframes are
    distinct competitors. 5-min (primary) models are returned first.

    Scoped to a *context* ("live" default, or "offline" to watch a training run).
    Queries model_levels directly — does not require the in-memory pipeline to be
    loaded. Returns null signal when no predictions exist yet (no bars received).
    """
    context = _validate_context(context)
    try:
        rows = await conn.fetch(
            "SELECT model_name, timeframe, level, xp, streak, bars_learned FROM model_levels WHERE user_id=$1 AND context=$2",
            user.id, context,
        )
        levels_map = {(r["timeframe"], r["model_name"]): dict(r) for r in rows}
    except Exception as exc:
        logger.warning("list_models: could not load model_levels: %s", exc)
        levels_map = {}

    # Latest signals are cached per timeframe.
    cached_by_tf: dict[str, dict] = {}
    for tf in MODEL_TIMEFRAMES:
        try:
            cached_by_tf[tf] = await get_latest_predictions(redis, str(user.id), tf) or {}
        except Exception as exc:
            logger.warning("list_models: Redis unavailable for %s: %s", tf, exc)
            cached_by_tf[tf] = {}

    result = []
    for tf in MODEL_TIMEFRAMES:                       # 5min first (primary), then 1min
        for name in model_names_for(tf):
            row          = levels_map.get((tf, name), {})
            level        = row.get("level",       1)
            xp           = row.get("xp",          0)
            streak       = row.get("streak",       0)
            bars_learned = row.get("bars_learned", 0)
            rank         = level_to_rank(level)
            threshold    = xp_for_level(level)

            result.append({
                "id":        f"{name}:{tf}",
                "name":      name,
                "timeframe": tf,
                "context":   context,
                "primary":   tf == PRIMARY_TIMEFRAME,
                "signal":    cached_by_tf.get(tf, {}).get(name),   # None until first bar
                "level_info": {
                    "level":            level,
                    "xp":               xp,
                    "streak":           streak,
                    "bars_learned":     bars_learned,
                    "rank":             rank,
                    "xp_to_next":       max(0, threshold - xp),
                    "xp_progress_pct":  round(xp / threshold, 3) if threshold > 0 else 1.0,
                    "unlocked_settings": get_unlocked_settings(rank),
                },
            })
    return result


# ── Level leaderboard (must come before /{model_name} to avoid routing clash) ─

@router.get("/leaderboard/levels")
async def leaderboard_levels(
    context: str = DEFAULT_CONTEXT,
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> list[dict]:
    """All 20 models (both timeframes) ranked by level DESC, then XP DESC."""
    context = _validate_context(context)
    rows = []
    for tf in MODEL_TIMEFRAMES:
        try:
            pipeline = await get_pipeline(str(user.id), conn, tf, context)
        except Exception as exc:
            logger.error("leaderboard_levels: get_pipeline failed for %s: %s", tf, exc)
            raise HTTPException(503, "Pipeline not available — try again after the first bar is received")
        for name in pipeline.model_names:
            t = pipeline.xp_trackers[name]
            rows.append({"model_name": name, "timeframe": tf, "context": context,
                         "primary": tf == PRIMARY_TIMEFRAME,
                         "id": f"{name}:{tf}", "level": t.level, "xp": t.xp,
                         "rank": level_to_rank(t.level), "streak": t.streak})
    rows.sort(key=lambda r: (r["level"], r["xp"]), reverse=True)
    return rows


# ── P&L leaderboard ──────────────────────────────────────────────────────────

@router.get("/leaderboard")
async def leaderboard_pnl(
    context: str = DEFAULT_CONTEXT,
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> list[dict]:
    """All 20 models (both timeframes) ranked by today's simulated P&L."""
    context = _validate_context(context)
    result = []
    for tf in MODEL_TIMEFRAMES:
        pipeline = _pipelines.get((str(user.id), tf, context))
        tm    = pipeline.trade_manager if pipeline else None
        names = pipeline.model_names if pipeline else model_names_for(tf)
        for name in names:
            stats = tm.get_session_stats(name) if tm else {
                "points": 0.0, "wins": 0, "losses": 0, "trades": 0
            }
            trade_count = stats["trades"]
            wins        = stats["wins"]
            win_rate    = round(wins / trade_count, 3) if trade_count else 0.0
            result.append({
                "model_name":  name,
                "timeframe":   tf,
                "context":     context,
                "primary":     tf == PRIMARY_TIMEFRAME,
                "id":          f"{name}:{tf}",
                "pnl_points":  round(stats["points"], 2),
                "pnl_dollars": round(stats["points"] * 5.0, 2),
                "trade_count": trade_count,
                "win_rate":    win_rate,
            })

    result.sort(key=lambda x: x["pnl_points"], reverse=True)
    return result


# ── LSTM (Model 11) — training + status ───────────────────────────────────────
# Defined before the generic /{model_name} routes for clarity. The path
# suffixes (train/status) are unique so there is no routing clash.

@router.post("/lstm/train")
async def train_lstm_endpoint(
    user: User = Depends(get_current_user),
    conn       = Depends(get_db),
) -> dict:
    """Manually trigger LSTM batch training on the user's full history."""
    from app.services.ml.lstm_trainer import train_lstm, count_available_bars
    from app.services.ml.lstm_model import MIN_BARS_TO_ACTIVATE

    bars = await count_available_bars(conn, str(user.id))
    if bars < MIN_BARS_TO_ACTIVATE:
        return {
            "success":        False,
            "reason":         "insufficient_data",
            "bars_available": bars,
            "bars_needed":    MIN_BARS_TO_ACTIVATE,
            "message":        f"Need {MIN_BARS_TO_ACTIVATE - bars} more bars before training",
        }

    # Train (CPU, synchronous — typically under a minute on 2000+ bars)
    result = await train_lstm(conn, str(user.id))

    # Reload the freshly-trained weights into the live 5-min pipeline, if loaded
    pipeline = _pipelines.get((str(user.id), LSTM_TIMEFRAME, "live"))
    if pipeline and pipeline.lstm is not None and result.get("success"):
        try:
            row = await conn.fetchrow(
                "SELECT state FROM model_state WHERE user_id=$1 AND model_name='lstm' AND timeframe=$2 AND context='live'",
                user.id, LSTM_TIMEFRAME,
            )
            if row:
                pipeline.lstm.load(row["state"])
        except Exception as exc:
            logger.warning("train_lstm: reload into live pipeline failed: %s", exc)

    return result


@router.get("/lstm/status")
async def lstm_status(
    user: User = Depends(get_current_user),
    conn       = Depends(get_db),
) -> dict:
    """LSTM training status and data-availability progress."""
    from app.services.ml.lstm_trainer import count_available_bars, get_lstm_progress
    from app.services.ml.lstm_model import MIN_BARS_TO_ACTIVATE

    try:
        bars = await count_available_bars(conn, str(user.id))
    except Exception as exc:
        logger.warning("lstm_status: bar count failed: %s", exc)
        bars = 0

    # Live per-epoch training snapshot (empty when not currently training).
    prog = get_lstm_progress(str(user.id))

    pipeline = _pipelines.get((str(user.id), LSTM_TIMEFRAME, "live"))
    is_trained = False
    last_trained = None
    train_accuracy = None
    train_samples = None
    if pipeline and pipeline.lstm is not None:
        lstm = pipeline.lstm
        is_trained = lstm.is_trained
        last_trained = lstm.last_trained.isoformat() if lstm.last_trained else None
        train_accuracy = lstm.train_accuracy
        train_samples = lstm.train_samples

    return {
        "is_trained":     is_trained,
        "is_dormant":     bars < MIN_BARS_TO_ACTIVATE,
        "timeframe":      LSTM_TIMEFRAME,   # the LSTM trades the 5-min series
        "bars_available": bars,
        "bars_needed":    MIN_BARS_TO_ACTIVATE,
        "progress_pct":   min(round(bars / MIN_BARS_TO_ACTIVATE * 100, 1), 100),
        "last_trained":   last_trained,
        "train_accuracy": train_accuracy,
        "train_samples":  train_samples,
        # ── Live per-epoch training progress (null when not training) ──────────
        # Field names match what the AFK status ticker reads directly.
        "training":       prog.get("training", False),
        "epoch":          prog.get("epoch"),
        "total_epochs":   prog.get("total_epochs"),
        "current_loss":   prog.get("current_loss"),
        "val_accuracy":   prog.get("val_accuracy"),
    }


# ── Promotion (offline → live) ────────────────────────────────────────────────
# The ONLY path from offline (history-trained) weights to live trading. Nothing
# is ever promoted automatically. Weights are copied; live LEVELS/XP are kept as
# they are (the offline run's level ladder is a training artifact, not live
# standing) — documented choice. The LSTM is excluded (it is batch-trained
# directly to live via /models/lstm/train, orthogonal to this flow).


def _zero_stats() -> dict:
    return {"points": 0.0, "wins": 0, "losses": 0, "trades": 0}


@router.get("/promotion-preview")
async def promotion_preview(
    timeframe: str = "all",
    user: User = Depends(get_current_user),
    conn       = Depends(get_db),
) -> dict:
    """
    "Should I promote?" comparison: for each model, offline vs live bars_learned
    (from model_levels) plus any in-memory simulated P&L/win-rate from the live
    and offline pipelines. Cheap — reads what is already available.
    """
    tfs = MODEL_TIMEFRAMES if timeframe == "all" else [timeframe]

    async def _levels(ctx: str, tf: str) -> dict:
        rows = await conn.fetch(
            "SELECT model_name, bars_learned, level FROM model_levels "
            "WHERE user_id=$1 AND timeframe=$2 AND context=$3",
            user.id, tf, ctx,
        )
        return {r["model_name"]: dict(r) for r in rows}

    models = []
    offline_exists = False
    for tf in tfs:
        live_lv = await _levels("live", tf)
        off_lv  = await _levels("offline", tf)
        if off_lv:
            offline_exists = True
        live_pl = _pipelines.get((str(user.id), tf, "live"))
        off_pl  = _pipelines.get((str(user.id), tf, "offline"))
        for name in model_names_for(tf):
            live_s = (live_pl.trade_manager.get_session_stats(name) if live_pl else _zero_stats())
            off_s  = (off_pl.trade_manager.get_session_stats(name)  if off_pl  else _zero_stats())
            models.append({
                "id":        f"{name}:{tf}",
                "model_name": name,
                "timeframe":  tf,
                "offline_ready": name in off_lv or off_pl is not None,
                "live": {
                    "bars_learned": live_lv.get(name, {}).get("bars_learned", 0),
                    "pnl_points":   round(live_s["points"], 2),
                    "wins":         live_s["wins"],
                    "losses":       live_s["losses"],
                },
                "offline": {
                    "bars_learned": off_lv.get(name, {}).get("bars_learned", 0),
                    "pnl_points":   round(off_s["points"], 2),
                    "wins":         off_s["wins"],
                    "losses":       off_s["losses"],
                },
            })
    return {"timeframe": timeframe, "offline_exists": offline_exists, "models": models}


@router.post("/promote")
async def promote_offline_to_live(
    body: dict,
    user: User = Depends(get_current_user),
    conn       = Depends(get_db),
) -> dict:
    """
    Promote OFFLINE-trained weights to LIVE for a timeframe (or all).
    Body: {"timeframe": "5min"|"1min"|"all", "confirm": "PROMOTE"}.

    Copies the offline online-model weights into the live context, persists them,
    and evicts the in-memory live pipeline so the new weights load on the next
    bar. Live levels/XP are intentionally left untouched. The LSTM is excluded.
    Nothing happens without confirm == "PROMOTE".
    """
    if body.get("confirm") != "PROMOTE":
        raise HTTPException(400, 'Promotion requires {"confirm": "PROMOTE"}.')
    timeframe = body.get("timeframe", "all")
    if timeframe != "all" and timeframe not in MODEL_TIMEFRAMES:
        raise HTTPException(400, f"Invalid timeframe '{timeframe}'. Use one of {MODEL_TIMEFRAMES} or 'all'.")
    tfs = MODEL_TIMEFRAMES if timeframe == "all" else [timeframe]

    from app.services.ml.pipeline import _pipelines, _pipeline_locks

    promoted: dict[str, int] = {}
    for tf in tfs:
        # Flush the in-memory offline pipeline first so its latest learning is
        # captured in model_state before we copy from it.
        off_pl = _pipelines.get((str(user.id), tf, "offline"))
        if off_pl is not None:
            try:
                await off_pl.save_state(conn)
            except Exception as exc:
                logger.warning("promote: offline snapshot failed for %s: %s", tf, exc)

        tag = await conn.execute(
            """INSERT INTO model_state (user_id, model_name, timeframe, context, state, bars_count, updated_at)
               SELECT user_id, model_name, timeframe, 'live', state, bars_count, NOW()
               FROM   model_state
               WHERE  user_id = $1 AND timeframe = $2 AND context = 'offline'
                 AND  model_name <> 'lstm'
               ON CONFLICT (user_id, model_name, timeframe, context)
               DO UPDATE SET state      = EXCLUDED.state,
                             bars_count = EXCLUDED.bars_count,
                             updated_at = NOW()""",
            user.id, tf,
        )
        try:
            promoted[tf] = int(tag.split()[-1])
        except (ValueError, IndexError, AttributeError):
            promoted[tf] = 0

        # Evict the live pipeline so it reloads the promoted weights on next bar.
        _pipelines.pop((str(user.id), tf, "live"), None)
        _pipeline_locks.pop((str(user.id), tf, "live"), None)

    total = sum(promoted.values())
    if total == 0:
        return {
            "promoted": False,
            "models_promoted": promoted,
            "message": "No offline weights found to promote. Run an OFFLINE training import first.",
        }
    return {
        "promoted": True,
        "models_promoted": promoted,
        "message": f"Promoted {total} offline model(s) to live. Live pipeline reloads on the next bar.",
    }


# ── Single model level ────────────────────────────────────────────────────────

@router.get("/{model_name}/level")
async def get_model_level(
    model_name: str,
    timeframe:  str = PRIMARY_TIMEFRAME,
    context:    str = DEFAULT_CONTEXT,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> dict:
    """
    Current XP, level, streak, rank, unlocked settings for one model on
    *timeframe*/*context*. Fast path: returns from in-memory pipeline if loaded.
    Fallback: queries model_levels table directly; uses level-1 defaults on error.
    """
    _validate_model_name(model_name)
    context = _validate_context(context)

    # Fast path — pipeline already in memory (bars have arrived)
    pipeline = _pipelines.get((str(user.id), timeframe, context))
    if pipeline and model_name in pipeline.xp_trackers:
        return pipeline.xp_trackers[model_name].to_dict()

    # Slow path — query DB directly (no need to initialise the whole pipeline)
    try:
        row = await conn.fetchrow(
            "SELECT level, xp, streak, bars_learned FROM model_levels WHERE user_id=$1 AND model_name=$2 AND timeframe=$3 AND context=$4",
            user.id, model_name, timeframe, context,
        )
    except Exception as exc:
        logger.warning("get_model_level: DB query failed for user %s: %s", user.id, exc)
        row = None

    tracker = XPTracker(
        str(user.id), model_name,
        level        = row["level"]        if row else 1,
        xp           = row["xp"]           if row else 0,
        streak       = row["streak"]       if row else 0,
        bars_learned = row["bars_learned"] if row else 0,
    )
    return tracker.to_dict()


# ── Model settings ────────────────────────────────────────────────────────────

@router.get("/{model_name}/settings")
async def get_settings(
    model_name: str,
    timeframe:  str = PRIMARY_TIMEFRAME,
    context:    str = DEFAULT_CONTEXT,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> dict:
    """
    Return behavior settings for one model on *timeframe*/*context*, annotated
    with lock status. Settings are per-(timeframe, context). Uses in-memory
    pipeline settings if loaded; otherwise falls back to hardcoded defaults.
    Never raises — new users always get a valid response.
    """
    _validate_model_name(model_name)
    context = _validate_context(context)

    # Determine rank (needed for lock annotations)
    raw  = None
    rank = "Rookie"

    pipeline = _pipelines.get((str(user.id), timeframe, context))
    if pipeline:
        rank = pipeline.level_ranks.get(model_name, "Rookie")
        try:
            raw = _get_model(pipeline, model_name).get_settings()
        except Exception as exc:
            logger.warning("get_settings: get_settings() failed on live pipeline: %s", exc)
            raw = None

    if raw is None:
        raw = _DEFAULT_SETTINGS.get(
            model_name,
            {"min_confidence": 0.60, "max_signals_per_session": 20, "signal_mode": "balanced"},
        )

    annotated = {}
    for key, val in raw.items():
        required_rank = _RANK_LOCKED_SETTINGS.get(key)
        locked = bool(required_rank and not _rank_gte(rank, required_rank))
        annotated[key] = {
            "value":         val,
            "locked":        locked,
            "requires_rank": required_rank,
        }
    return annotated


@router.put("/{model_name}/settings")
async def update_settings(
    model_name:   str,
    new_settings: dict,
    timeframe:    str = PRIMARY_TIMEFRAME,
    context:      str = DEFAULT_CONTEXT,
    user: User    = Depends(get_current_user),
    conn          = Depends(get_db),
) -> dict:
    """
    Update behavior settings for one model on *timeframe*/*context* (settings are
    per-(timeframe, context)). Raises 403 if attempting to change a setting locked
    at the model's current rank.
    """
    _validate_model_name(model_name)
    context = _validate_context(context)
    if model_name == "lstm":
        raise HTTPException(
            400, "LSTM is batch-trained and has no tunable per-bar settings. "
                 "Use POST /models/lstm/train to retrain it.",
        )
    _validate_settings_values(new_settings)
    pipeline = await get_pipeline(str(user.id), conn, timeframe, context)
    rank     = pipeline.level_ranks[model_name]

    for key in new_settings:
        required_rank = _RANK_LOCKED_SETTINGS.get(key)
        if required_rank and not _rank_gte(rank, required_rank):
            raise HTTPException(
                403,
                f"Setting '{key}' requires rank {required_rank} "
                f"(current rank: {rank})",
            )

    _get_model(pipeline, model_name).update_settings(new_settings)
    return {"status": "updated", "model_name": model_name, "timeframe": timeframe,
            "context": context, "settings": new_settings}


# ── Model reset ───────────────────────────────────────────────────────────────

@router.post("/{model_name}/reset")
async def reset_model(
    model_name: str,
    timeframe:  str = PRIMARY_TIMEFRAME,
    context:    str = DEFAULT_CONTEXT,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> dict:
    """Reset River model weights for one model on *timeframe*/*context*. Level/XP preserved."""
    _validate_model_name(model_name)
    context = _validate_context(context)
    if model_name == "lstm":
        raise HTTPException(
            400, "LSTM is batch-trained — it has no online weights to reset. "
                 "Use POST /models/lstm/train to retrain it from history.",
        )
    pipeline = await get_pipeline(str(user.id), conn, timeframe, context)
    _get_model(pipeline, model_name).reset()
    pipeline.drift_detectors[model_name].reset()
    return {
        "message":   f"Model '{model_name}' ({timeframe}/{context}) weights reset. Level and XP preserved.",
        "timeframe": timeframe,
        "context":   context,
        "level":     pipeline.xp_trackers[model_name].level,
    }


# ── Model accuracy history ────────────────────────────────────────────────────

@router.get("/{model_name}/history")
async def model_history(
    model_name: str,
    timeframe:  str      = PRIMARY_TIMEFRAME,
    context:    str      = DEFAULT_CONTEXT,
    from_ts:    datetime = None,
    to_ts:      datetime = None,
    limit:      int      = 200,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> list[dict]:
    """Prediction history for one model on *timeframe*/*context* with outcomes.
    Offline predictions are the is_training=true rows; live are is_training=false."""
    _validate_model_name(model_name)
    context = _validate_context(context)
    if limit > 1000:
        raise HTTPException(400, "limit must be ≤ 1000")

    from_ts = from_ts or datetime(2000, 1, 1, tzinfo=timezone.utc)
    to_ts   = to_ts   or datetime.now(tz=timezone.utc)

    try:
        rows = await conn.fetch(
            """SELECT time, signal, confidence, actual_outcome
               FROM   predictions
               WHERE  user_id    = $1
                 AND  model_name = $2
                 AND  timeframe  = $3
                 AND  is_training = $4
                 AND  time      >= $5
                 AND  time      <= $6
               ORDER  BY time DESC
               LIMIT  $7""",
            user.id, model_name, timeframe, context == "offline", from_ts, to_ts, limit,
        )
    except Exception as exc:
        logger.error("model_history: DB query failed for user %s model %s: %s", user.id, model_name, exc)
        raise HTTPException(503, "Database unavailable — try again shortly")
    return [
        {
            "time":           r["time"].isoformat(),
            "signal":         r["signal"],
            "confidence":     r["confidence"],
            "actual_outcome": r["actual_outcome"],
        }
        for r in rows
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_SIGNAL_MODES = {"aggressive", "balanced", "conservative"}

_SETTING_RANGES: dict[str, tuple] = {
    "min_confidence":          (0.0,  1.0),
    "atr_stop_mult":           (0.1,  10.0),
    "atr_target_mult":         (0.1,  20.0),
    "learning_rate":           (0.001, 1.0),
    "max_signals_per_session": (1,    200),
    "rsi_overbought":          (50,   100),
    "rsi_oversold":            (0,    50),
    "volume_spike_threshold":  (0.5,  10.0),
    "delta_imbalance_cutoff":  (0.0,  1.0),
    "user_weight":             (0.0,  1.0),
}


def _validate_settings_values(settings: dict) -> None:
    """Raise 400 if any setting value is outside its sane range."""
    for key, val in settings.items():
        if key == "signal_mode":
            if val not in _VALID_SIGNAL_MODES:
                raise HTTPException(
                    400,
                    f"Invalid signal_mode '{val}'. Must be one of: {sorted(_VALID_SIGNAL_MODES)}",
                )
            continue
        if key == "auto_blend":
            if not isinstance(val, bool):
                raise HTTPException(400, f"'{key}' must be a boolean")
            continue
        bounds = _SETTING_RANGES.get(key)
        if bounds and isinstance(val, (int, float)):
            lo, hi = bounds
            if not (lo <= val <= hi):
                raise HTTPException(
                    400,
                    f"Setting '{key}' value {val} is out of range [{lo}, {hi}]",
                )


def _validate_model_name(name: str) -> None:
    if name not in ALL_MODEL_NAMES:
        raise HTTPException(
            404,
            f"Unknown model '{name}'. Valid names: {ALL_MODEL_NAMES}",
        )


def _validate_context(context: str) -> str:
    if context not in VALID_CONTEXTS:
        raise HTTPException(
            400, f"Invalid context '{context}'. Must be one of: {list(VALID_CONTEXTS)}",
        )
    return context


def _get_model(pipeline, name: str):
    """Return the Champion model object (or personal model)."""
    if name == "personal":
        return pipeline.personal
    cc = pipeline.cc_models.get(name)
    return cc._champion_model_obj if cc else None
