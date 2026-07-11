"""
System MODE routes (per user) — the source of truth for ONLINE vs OFFLINE.

The system is in exactly ONE mode at a time:

  LIVE (default) — trades forward real-time data. Live bar closes enter the 'live'
                   context; historical ("hist") bars are refused at the gate.
  OFFLINE        — trains on history. "hist" bars enter the SEPARATE 'offline'
                   context (a copy of the live models that learns independently,
                   is_training-tagged, watermark bypassed); live bars are refused.

Switching modes requires the ingestion queue to be DRAINED so a switch can't mix
historical and live bars mid-stream. If bars are still queued the switch is
blocked (409); pass {"flush": true} to flush-and-switch.

  POST /mode/live     → switch to LIVE     (optional {"flush": true})
  POST /mode/offline  → switch to OFFLINE  (optional {"flush": true})
  GET  /mode          → { mode, queue_pending, can_switch, bars_ingested, ... }

This REPLACES the old training-mode flag. /training/* remain as thin aliases
(offline == the old training mode).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.redis import get_redis
from app.core.security import get_current_user
from app.models.user import User
from app.services.market_data.ingestion import (
    get_mode, set_mode, mode_status, MODE_LIVE, MODE_OFFLINE,
    get_queue_pending, flush_queue,
)

router = APIRouter()


class SwitchBody(BaseModel):
    flush: bool = False


async def _switch(user_id: str, target: str, flush: bool, redis) -> dict:
    """Switch to *target* mode, enforcing the drained-queue rule."""
    if get_mode(user_id) != target:
        pending = await get_queue_pending(redis)
        if pending > 0 and not flush:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "queue_not_drained",
                    "message": (
                        f"{pending} bar(s) still queued — drain or flush before switching "
                        f"to {target.upper()} mode so historical and live bars can't mix. "
                        'Retry with {"flush": true} to flush-and-switch.'
                    ),
                    "queue_pending": pending,
                },
            )
        flushed = await flush_queue(user_id, redis) if (pending > 0 and flush) else 0
        set_mode(user_id, target)
    else:
        flushed = 0

    st = mode_status(user_id)
    st["queue_pending"] = await get_queue_pending(redis)
    if flushed:
        st["flushed"] = flushed
    return st


@router.post("/live")
async def switch_to_live(
    body: SwitchBody = SwitchBody(),
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> dict:
    """Switch to LIVE mode (blocked if bars are queued unless flush=true)."""
    return await _switch(str(user.id), MODE_LIVE, body.flush, redis)


@router.post("/offline")
async def switch_to_offline(
    body: SwitchBody = SwitchBody(),
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> dict:
    """Switch to OFFLINE mode (blocked if bars are queued unless flush=true)."""
    return await _switch(str(user.id), MODE_OFFLINE, body.flush, redis)


@router.get("")
async def get_current_mode(
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> dict:
    """Current mode plus why-blocked info: queue depth and whether a switch is free."""
    st = mode_status(str(user.id))
    pending = await get_queue_pending(redis)
    st["queue_pending"] = pending
    st["can_switch"] = pending == 0        # a switch with bars queued needs flush=true
    st["modes"] = [MODE_LIVE, MODE_OFFLINE]
    return st
