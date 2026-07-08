"""
Ingestion arm-gate routes (per user).

Enabling the NinjaTrader strategy immediately streams bars over TCP. The arm gate
decides WHEN those bars enter the pipeline: while disarmed (the default) every
incoming bar is refused at the TCP intake — never queued, never stored — so a
connected strategy doesn't stack the queue. Arming opens the gate.

This is independent of training mode: arming controls whether bars enter the
pipeline at all; training mode controls whether accepted historical/out-of-order
bars bypass the live watermark.

  POST /ingestion/arm     → start accepting incoming strategy bars
  POST /ingestion/disarm  → refuse incoming bars; optional {"flush": true} also
                            clears anything already queued (stop-and-clear)
  GET  /ingestion/status  → { armed, queue_pending }
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.redis import get_redis
from app.core.security import get_current_user
from app.models.user import User
from app.services.market_data.ingestion import (
    arm_ingestion,
    disarm_ingestion,
    ingestion_armed_status,
    flush_queue,
    get_queue_pending,
)

router = APIRouter()


class DisarmBody(BaseModel):
    flush: bool = False


@router.post("/arm")
async def arm(user: User = Depends(get_current_user), redis=Depends(get_redis)) -> dict:
    """Arm ingestion — incoming strategy bars start flowing into the pipeline."""
    st = arm_ingestion(str(user.id))
    st["queue_pending"] = await get_queue_pending(redis)
    return st


@router.post("/disarm")
async def disarm(
    body: DisarmBody = DisarmBody(),
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> dict:
    """
    Disarm ingestion — incoming strategy bars are refused (not queued/stored).
    With {"flush": true} also drop anything already queued so the user can
    stop-and-clear in one action.
    """
    st = disarm_ingestion(str(user.id))
    if body.flush:
        st["flushed"] = await flush_queue(str(user.id), redis)
    st["queue_pending"] = await get_queue_pending(redis)
    return st


@router.get("/status")
async def status(user: User = Depends(get_current_user), redis=Depends(get_redis)) -> dict:
    """Armed flag plus queue_pending (bars still buffered in the shared stream)."""
    st = ingestion_armed_status(str(user.id))
    st["queue_pending"] = await get_queue_pending(redis)
    return st
