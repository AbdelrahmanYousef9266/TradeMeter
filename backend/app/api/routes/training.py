"""
Training Mode routes (per user).

Training mode replays historical sessions through the same NinjaTrader playback
feed. While it is ON, the ingestion pipeline bypasses the live monotonic
watermark (so past / out-of-order bars are accepted), does NOT advance the live
watermark, and tags every stored tick/prediction is_training=true so the replay
never pollutes the live dataset or the live chart/coverage views. Models still
learn from the replayed bars — that is the whole point.

  POST /training/start  → turn training mode ON  (resets this-run counters)
  POST /training/stop   → turn training mode OFF
  GET  /training/status → { training, bars_ingested, sessions_ingested }
"""

from fastapi import APIRouter, Depends

from app.core.redis import get_redis
from app.core.security import get_current_user
from app.models.user import User
from app.services.market_data.ingestion import (
    start_training,
    stop_training,
    training_status,
    flush_queue,
    get_queue_pending,
)

router = APIRouter()


@router.post("/start")
async def start(user: User = Depends(get_current_user)) -> dict:
    """Turn training mode ON for the current user and reset this-run counters."""
    return start_training(str(user.id))


@router.post("/stop")
async def stop(user: User = Depends(get_current_user)) -> dict:
    """Turn training mode OFF for the current user."""
    return stop_training(str(user.id))


@router.get("/status")
async def status(user: User = Depends(get_current_user), redis=Depends(get_redis)) -> dict:
    """
    Training mode flag + this-run counters, plus queue_pending: how many bars are
    still queued in the shared ingestion stream (drives the progress indicator).
    """
    st = training_status(str(user.id))
    st["queue_pending"] = await get_queue_pending(redis)
    return st


@router.post("/flush-queue")
async def flush(user: User = Depends(get_current_user), redis=Depends(get_redis)) -> dict:
    """
    Discard everything queued in the ingestion stream and clear the user's
    deferred trade state. Safe: dropped bars are re-importable via gap-fill.
    NOTE: the stream is shared, so this flushes the queue for the whole backend
    (acceptable for this 1–2 user deployment).
    """
    dropped = await flush_queue(str(user.id), redis)
    return {"flushed": dropped}
