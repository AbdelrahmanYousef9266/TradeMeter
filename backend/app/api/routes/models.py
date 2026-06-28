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
    """All 10 models with current signal from Redis cache + level info."""
    pipeline = await get_pipeline(str(user.id), conn)
    cached   = await get_latest_predictions(redis, str(user.id)) or {}

    result = []
    for name in ALL_MODEL_NAMES:
        tracker = pipeline.xp_trackers[name]
        signal_info = cached.get(name, {})
        result.append({
            "model_name":      name,
            "rank":            level_to_rank(tracker.level),
            "level":           tracker.level,
            "xp_progress_pct": tracker.to_dict()["xp_progress_pct"],
            "signal":          signal_info.get("signal", "HOLD"),
            "confidence":      signal_info.get("confidence", 0.0),
            "streak":          tracker.streak,
            "bars_learned":    tracker.bars_learned,
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
    """Models ranked by today's prediction accuracy (correct direction %)."""
    today = datetime.now(tz=timezone.utc).date()
    rows = await conn.fetch(
        """SELECT model_name,
                  COUNT(*) FILTER (WHERE actual_outcome IS NOT NULL) AS total,
                  COUNT(*) FILTER (
                      WHERE actual_outcome IS NOT NULL
                        AND ((signal='BUY'  AND actual_outcome='up')
                          OR (signal='SELL' AND actual_outcome='down'))
                  ) AS correct
           FROM predictions
           WHERE user_id = $1
             AND time >= $2::date
           GROUP BY model_name""",
        user.id, today,
    )
    result = []
    for row in rows:
        total = row["total"] or 0
        correct = row["correct"] or 0
        acc = correct / total if total else 0.0
        result.append({"model_name": row["model_name"], "accuracy_today": round(acc, 4), "total": total})
    result.sort(key=lambda r: r["accuracy_today"], reverse=True)
    return result


# ── Single model level ────────────────────────────────────────────────────────

@router.get("/{model_name}/level")
async def get_model_level(
    model_name: str,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> dict:
    """Current XP, level, streak, rank, unlocked settings for one model."""
    _validate_model_name(model_name)
    pipeline = await get_pipeline(str(user.id), conn)
    return pipeline.xp_trackers[model_name].to_dict()


# ── Model settings ────────────────────────────────────────────────────────────

@router.get("/{model_name}/settings")
async def get_settings(
    model_name: str,
    user: User  = Depends(get_current_user),
    conn        = Depends(get_db),
) -> dict:
    """
    Return behavior settings for one model.
    Each setting is annotated with lock status based on the model's current rank.
    """
    _validate_model_name(model_name)
    pipeline = await get_pipeline(str(user.id), conn)
    rank     = pipeline.level_ranks[model_name]
    unlocked = get_unlocked_settings(rank)

    raw = _get_model(pipeline, model_name).get_settings()
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
