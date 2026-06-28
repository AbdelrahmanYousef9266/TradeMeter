"""
Market data routes:
  GET /market/history  → paginated OHLCV bar history for a symbol
  WS  /market/live     → real-time bar/tick feed via Redis pub/sub
"""

import asyncio
import logging
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from app.core.security import decode_jwt, get_current_user
from app.db.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ── REST: history ───────────────────────────────────────────────────────────

@router.get("/history")
async def get_history(
    symbol: str,
    from_ts: datetime,
    to_ts: datetime,
    limit: int = 500,
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> list[dict]:
    """
    Return OHLCV bar closes for *symbol* between *from_ts* and *to_ts*,
    scoped to the authenticated user.
    """
    if limit > 5000:
        raise HTTPException(400, "limit must be ≤ 5000")

    rows = await conn.fetch(
        """SELECT time, symbol, open, high, low, close, volume, bar_type
           FROM   ticks
           WHERE  user_id = $1
             AND  symbol  = $2
             AND  time   >= $3
             AND  time   <= $4
           ORDER  BY time ASC
           LIMIT  $5""",
        user.id, symbol, from_ts, to_ts, limit,
    )

    return [
        {
            "time":     row["time"].isoformat(),
            "symbol":   row["symbol"],
            "open":     row["open"],
            "high":     row["high"],
            "low":      row["low"],
            "close":    row["close"],
            "volume":   row["volume"],
            "bar_type": row["bar_type"],
        }
        for row in rows
    ]


# ── WebSocket: live feed ────────────────────────────────────────────────────

@router.websocket("/live")
async def websocket_live(websocket: WebSocket) -> None:
    """
    Real-time bar and tick feed.

    Auth: reads 'tm_session' cookie and validates the JWT.
    Data: subscribes to Redis pub/sub channel 'live:{user_id}' and forwards
          every JSON payload published by the TCP listener.
    """
    token = websocket.cookies.get("tm_session")
    if not token:
        await websocket.close(code=4001, reason="Not authenticated")
        return

    try:
        payload = decode_jwt(token)
        user_id = payload["sub"]
    except HTTPException:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    logger.info("WebSocket: user %s connected", user_id)

    redis_client: aioredis.Redis = websocket.app.state.redis
    pubsub = redis_client.pubsub()
    channel = f"live:{user_id}"

    await pubsub.subscribe(channel)

    async def _forward():
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await websocket.send_text(message["data"])
        except Exception:
            pass

    async def _watch_disconnect():
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

    forward_task    = asyncio.create_task(_forward())
    disconnect_task = asyncio.create_task(_watch_disconnect())

    done, pending = await asyncio.wait(
        {forward_task, disconnect_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    try:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
    except Exception:
        pass

    logger.info("WebSocket: user %s disconnected", user_id)
