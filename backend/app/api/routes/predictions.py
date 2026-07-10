"""
Prediction endpoints:
  GET /predictions/latest  → cached latest signals for all 10 models
  GET /predictions/history → paginated past predictions with actual outcomes
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.core.redis import get_latest_predictions, get_redis
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/latest")
async def get_latest(
    timeframe: str = "5min",
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
    conn=Depends(get_db),
) -> dict:
    """
    Most recent signals for the models on *timeframe* (default 5-min, the primary
    trading timeframe). Served from Redis cache; falls back to DB on cache miss.
    """
    cached = await get_latest_predictions(redis, str(user.id), timeframe)
    if cached:
        return cached

    # Cache miss — fetch most recent prediction per model from DB (this timeframe)
    rows = await conn.fetch(
        """SELECT DISTINCT ON (model_name)
               model_name, signal, confidence, direction_up_prob,
               predicted_high, predicted_low, time
           FROM predictions
           WHERE user_id = $1 AND timeframe = $2
           ORDER BY model_name, time DESC""",
        user.id, timeframe,
    )
    return {
        row["model_name"]: {
            "signal":         row["signal"],
            "confidence":     row["confidence"],
            "direction_up":   row["direction_up_prob"],
            "predicted_high": row["predicted_high"],
            "predicted_low":  row["predicted_low"],
            "time":           row["time"].isoformat(),
        }
        for row in rows
    }


@router.get("/history")
async def get_history(
    model_name: str | None  = Query(None),
    timeframe:  str         = Query("5min"),
    from_ts:    datetime    = Query(...),
    to_ts:      datetime    = Query(...),
    limit:      int         = Query(100, le=1000),
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> list[dict]:
    """
    Past predictions with actual_outcome filled, scoped to *timeframe*.
    Filter by model_name, time range, and limit.
    """
    if model_name:
        rows = await conn.fetch(
            """SELECT time, model_name, signal, confidence, direction_up_prob,
                      predicted_high, predicted_low, actual_outcome
               FROM   predictions
               WHERE  user_id    = $1
                 AND  model_name = $2
                 AND  timeframe  = $3
                 AND  time      >= $4
                 AND  time      <= $5
               ORDER  BY time DESC
               LIMIT  $6""",
            user.id, model_name, timeframe, from_ts, to_ts, limit,
        )
    else:
        rows = await conn.fetch(
            """SELECT time, model_name, signal, confidence, direction_up_prob,
                      predicted_high, predicted_low, actual_outcome
               FROM   predictions
               WHERE  user_id = $1
                 AND  timeframe = $2
                 AND  time   >= $3
                 AND  time   <= $4
               ORDER  BY time DESC
               LIMIT  $5""",
            user.id, timeframe, from_ts, to_ts, limit,
        )

    return [
        {
            "time":           row["time"].isoformat(),
            "model_name":     row["model_name"],
            "signal":         row["signal"],
            "confidence":     row["confidence"],
            "direction_up":   row["direction_up_prob"],
            "predicted_high": row["predicted_high"],
            "predicted_low":  row["predicted_low"],
            "actual_outcome": row["actual_outcome"],
        }
        for row in rows
    ]
