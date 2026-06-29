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
from app.services.ml.pipeline import get_pipeline, ALL_MODEL_NAMES, _pipelines
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
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
    conn=Depends(get_db),
) -> list[dict]:
    """
    All 9 models with level info (from DB) + latest prediction signal (from Redis).
    Queries model_levels directly — does not require the in-memory pipeline to be loaded.
    Returns null signal when no predictions exist yet (no bars received).
    """
    try:
        rows = await conn.fetch(
            "SELECT model_name, level, xp, streak, bars_learned FROM model_levels WHERE user_id=$1",
            user.id,
        )
        levels_map = {r["model_name"]: dict(r) for r in rows}
    except Exception as exc:
        logger.warning("list_models: could not load model_levels: %s", exc)
        levels_map = {}

    try:
        cached = await get_latest_predictions(redis, str(user.id)) or {}
    except Exception as exc:
        logger.warning("list_models: Redis unavailable: %s", exc)
        cached = {}

    result = []
    for name in ALL_MODEL_NAMES:
        row          = levels_map.get(name, {})
        level        = row.get("level",       1)
        xp           = row.get("xp",          0)
        streak       = row.get("streak",       0)
        bars_learned = row.get("bars_learned", 0)
        rank         = level_to_rank(level)
        threshold    = xp_for_level(level)

        result.append({
            "name":   name,
            "signal": cached.get(name),     # None until first bar is processed
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
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> list[dict]:
    """All models ranked by level DESC, then XP DESC."""
    pipeline = await get_pipeline(str(user.id), conn)
    rows = []
    for name in ALL_MODEL_NAMES:
        t = pipeline.xp_trackers[name]
        rows.append({"model_name": name, "level": t.level, "xp": t.xp,
                     "rank": level_to_rank(t.level), "streak": t.streak})
    rows.sort(key=lambda r: (r["level"], r["xp"]), reverse=True)
    return rows


# ── P&L leaderboard ──────────────────────────────────────────────────────────

@router.get("/leaderboard")
async def leaderboard_pnl(
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> list[dict]:
    """Models ranked by today's simulated P&L (Level 3 trade outcomes)."""
    pipeline = _pipelines.get(str(user.id))

    if pipeline:
        session_pnl   = pipeline.trade_manager.get_session_pnl()
        closed_trades = pipeline.trade_manager.closed_trades
    else:
        session_pnl   = {}
        closed_trades = []

    result = []
    for name in ALL_MODEL_NAMES:
        pnl        = session_pnl.get(name, 0.0)
        trade_count = sum(1 for t in closed_trades if t.model_name == name)
        wins        = sum(1 for t in closed_trades if t.model_name == name and t.won)
        win_rate    = round(wins / trade_count, 3) if trade_count else 0.0
        result.append({
            "model_name":  name,
            "pnl_points":  round(pnl, 2),
            "pnl_dollars": round(pnl * 5.0, 2),
            "trade_count": trade_count,
            "win_rate":    win_rate,
        })

    result.sort(key=lambda x: x["pnl_points"], reverse=True)
    return result


# ── Single model level ────────────────────────────────────────────────────────

@router.get("/{model_name}/level")
async def get_model_level(
    model_name: str,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> dict:
    """
    Current XP, level, streak, rank, unlocked settings for one model.
    Fast path: returns from in-memory pipeline if loaded.
    Fallback: queries model_levels table directly; uses level-1 defaults on any error.
    """
    _validate_model_name(model_name)

    # Fast path — pipeline already in memory (bars have arrived)
    pipeline = _pipelines.get(str(user.id))
    if pipeline:
        return pipeline.xp_trackers[model_name].to_dict()

    # Slow path — query DB directly (no need to initialise the whole pipeline)
    try:
        row = await conn.fetchrow(
            "SELECT level, xp, streak, bars_learned FROM model_levels WHERE user_id=$1 AND model_name=$2",
            user.id, model_name,
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
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> dict:
    """
    Return behavior settings for one model, annotated with lock status.
    Uses in-memory pipeline settings if loaded; otherwise falls back to hardcoded defaults.
    Never raises — new users always get a valid response.
    """
    _validate_model_name(model_name)

    # Determine rank (needed for lock annotations)
    raw  = None
    rank = "Rookie"

    pipeline = _pipelines.get(str(user.id))
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
    user: User    = Depends(get_current_user),
    conn          = Depends(get_db),
) -> dict:
    """
    Update behavior settings.  Raises 403 if attempting to change a setting
    that is locked at the model's current rank.
    """
    _validate_model_name(model_name)
    pipeline = await get_pipeline(str(user.id), conn)
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
    return {"status": "updated", "model_name": model_name, "settings": new_settings}


# ── Model reset ───────────────────────────────────────────────────────────────

@router.post("/{model_name}/reset")
async def reset_model(
    model_name: str,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> dict:
    """Reset River model weights.  Level and XP are preserved."""
    _validate_model_name(model_name)
    pipeline = await get_pipeline(str(user.id), conn)
    _get_model(pipeline, model_name).reset()
    pipeline.drift_detectors[model_name].reset()
    return {
        "message": f"Model '{model_name}' weights reset. Level and XP preserved.",
        "level":   pipeline.xp_trackers[model_name].level,
    }


# ── Model accuracy history ────────────────────────────────────────────────────

@router.get("/{model_name}/history")
async def model_history(
    model_name: str,
    from_ts:    datetime = None,
    to_ts:      datetime = None,
    limit:      int      = 200,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> list[dict]:
    """Prediction history for one model with actual outcomes."""
    _validate_model_name(model_name)
    if limit > 1000:
        raise HTTPException(400, "limit must be ≤ 1000")

    from_ts = from_ts or datetime(2000, 1, 1, tzinfo=timezone.utc)
    to_ts   = to_ts   or datetime.now(tz=timezone.utc)

    rows = await conn.fetch(
        """SELECT time, signal, confidence, actual_outcome
           FROM   predictions
           WHERE  user_id    = $1
             AND  model_name = $2
             AND  time      >= $3
             AND  time      <= $4
           ORDER  BY time DESC
           LIMIT  $5""",
        user.id, model_name, from_ts, to_ts, limit,
    )
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

def _validate_model_name(name: str) -> None:
    if name not in ALL_MODEL_NAMES:
        raise HTTPException(
            404,
            f"Unknown model '{name}'. Valid names: {ALL_MODEL_NAMES}",
        )


def _get_model(pipeline, name: str):
    """Return the model object (handles both personality models and personal)."""
    return pipeline.models.get(name) or pipeline.personal
