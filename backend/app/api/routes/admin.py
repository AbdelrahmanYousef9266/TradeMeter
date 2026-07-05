"""
Admin routes — self-service only.

  POST /admin/reset-my-data → wipe the CURRENT user's learned state (and,
                              optionally, their raw bars). Can only ever reset
                              the caller's own data — user_id comes from the
                              session, never from the request body.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.user_reset import (
    count_user_data,
    reset_user_data,
    purge_in_memory_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ResetRequest(BaseModel):
    confirm: str
    include_bars: bool = False   # keep raw price bars by default (they're not biased)


@router.post("/reset-my-data")
async def reset_my_data(
    req: ResetRequest,
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> dict:
    """
    Delete the authenticated user's predictions, CC history, model levels, and
    all persisted model weights. Raw OHLCV bars are kept unless include_bars=true.

    Requires an explicit confirmation body: {"confirm": "RESET"}. After deletion
    the user's in-memory pipeline is evicted so the next bar rebuilds fresh state
    (level 1, dormant LSTM) rather than re-persisting the old, biased weights.
    """
    if req.confirm != "RESET":
        raise HTTPException(
            400,
            'Confirmation required — send {"confirm": "RESET"} to proceed.',
        )

    before  = await count_user_data(conn, user.id, include_bars=req.include_bars)
    deleted = await reset_user_data(conn, user.id, include_bars=req.include_bars)
    purge_in_memory_state(str(user.id))
    logger.info("Self-service reset for user %s (include_bars=%s)", user.id, req.include_bars)

    note = (
        "All price history was also deleted — starting from an empty slate."
        if req.include_bars else
        "Price bars were kept. Retrain via training mode to build clean learned "
        "state from your clean price history."
    )
    return {
        "status":       "reset_complete",
        "user_id":      str(user.id),
        "include_bars": req.include_bars,
        "counts_before": before,
        "deleted":      deleted,
        "note":         note,
    }
