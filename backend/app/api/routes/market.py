"""
Market data routes:
  GET /market/history      → paginated OHLCV bar history for a symbol
  GET /market/status       → current pipeline state (warmup/connection) for hydration
  GET /market/bars         → last N bar closes for chart hydration on page refresh
  GET /market/coverage     → per-day bar counts + LSTM training days (settings calendar, live only)
  GET /market/data-summary → whole-DB inventory: totals, months, live/training split (Data page)
  GET /market/data-days    → per-day detail for one month (Data page drill-down)
  WS  /market/live         → real-time bar/tick feed via Redis pub/sub
"""

import asyncio
import logging
import re
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from app.core.security import decode_jwt, get_current_user
from app.db.database import get_db
from app.models.user import User
from app.services.market_data.tcp_listener import _resolve_token

logger = logging.getLogger(__name__)
router = APIRouter()


# ── REST: history ───────────────────────────────────────────────────────────

@router.get("/history")
async def get_history(
    symbol: str,
    from_ts: datetime,
    to_ts: datetime,
    limit: int = 500,
    timeframe: str = "1min",
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> list[dict]:
    """
    Return OHLCV bar closes for *symbol* between *from_ts* and *to_ts*,
    scoped to the authenticated user and the given *timeframe*.
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
             AND  is_training = false
             AND  timeframe = $6
           ORDER  BY time ASC
           LIMIT  $5""",
        user.id, symbol, from_ts, to_ts, limit, timeframe,
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


# ── REST: pipeline status (for refresh hydration) ────────────────────────────

@router.get("/status")
async def market_status(
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> dict:
    """
    Current pipeline state for this user — used by the frontend to hydrate
    warmup/connection state on page load instead of waiting for the next
    WebSocket message.

    NOTE: The FeatureEngine's bar_count is in-memory only. On a page refresh the
    backend state is intact, so this returns the true (possibly post-warmup)
    count. But if the BACKEND restarts, the engine genuinely resets and warmup
    correctly restarts at 0 — the 50 bars of rolling indicator state must be
    rebuilt before features are valid again. That is expected, not a bug.
    """
    from app.services.market_data.features import _engines, _WARMUP_BARS
    from app.api.routes.auth import compute_nt_connected

    user_id = str(user.id)
    engine  = _engines.get(user_id)

    bars_received = engine.bar_count if engine else 0
    warming_up    = bars_received < _WARMUP_BARS

    nt_connected = False
    try:
        nt_connected = await compute_nt_connected(user, conn)
    except Exception:
        pass

    return {
        "warming_up":    warming_up,
        "bars_received": min(bars_received, _WARMUP_BARS) if warming_up else bars_received,
        "bars_needed":   _WARMUP_BARS,
        "nt_connected":  nt_connected,
    }


# ── REST: recent bars (for chart hydration) ──────────────────────────────────

@router.get("/bars")
async def recent_bars(
    limit: int = 200,
    timeframe: str = "1min",
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> list[dict]:
    """Last N bar closes (chronological) for chart hydration after a refresh."""
    limit = max(1, min(limit, 500))
    try:
        rows = await conn.fetch(
            """SELECT time, open, high, low, close, volume
               FROM   ticks
               WHERE  user_id = $1
                 AND  bar_type != 'tick'
                 AND  is_training = false
                 AND  timeframe = $3
               ORDER  BY time DESC
               LIMIT  $2""",
            user.id, limit, timeframe,
        )
    except Exception as exc:
        logger.warning("recent_bars: query failed for user %s: %s", user.id, exc)
        return []

    # Reverse into chronological order for the chart
    return [
        {
            "time":   r["time"].isoformat(),
            "open":   r["open"],
            "high":   r["high"],
            "low":    r["low"],
            "close":  r["close"],
            "volume": r["volume"],
        }
        for r in reversed(rows)
    ]


# ── REST: data coverage (settings calendar) ──────────────────────────────────

@router.get("/coverage")
async def data_coverage(
    timeframe: str = "1min",
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> dict:
    """
    Per-day summary of collected bars for this user, plus LSTM training days.
    Powers the settings data-coverage calendar. Scoped to *timeframe*.
    """
    # Bars per day (exclude ticks)
    try:
        day_rows = await conn.fetch(
            """SELECT date_trunc('day', time)::date AS day,
                      COUNT(*)  AS bars,
                      MIN(time) AS first_bar,
                      MAX(time) AS last_bar
               FROM   ticks
               WHERE  user_id = $1
                 AND  bar_type != 'tick'
                 AND  is_training = false
                 AND  timeframe = $2
               GROUP  BY date_trunc('day', time)::date
               ORDER  BY day ASC""",
            user.id, timeframe,
        )
    except Exception as exc:
        logger.warning("coverage: bars query failed for user %s: %s", user.id, exc)
        day_rows = []

    days = [
        {
            "date":  r["day"].isoformat(),
            "bars":  r["bars"],
            "first": r["first_bar"].isoformat() if r["first_bar"] else None,
            "last":  r["last_bar"].isoformat() if r["last_bar"] else None,
        }
        for r in day_rows
    ]

    # LSTM training days — model_state.updated_at for model_name='lstm' is a
    # reasonable proxy (no dedicated training-run table exists).
    trained_days = []
    try:
        lstm_rows = await conn.fetch(
            """SELECT date_trunc('day', updated_at)::date AS day
               FROM   model_state
               WHERE  user_id = $1
                 AND  model_name = 'lstm'
               GROUP  BY date_trunc('day', updated_at)::date""",
            user.id,
        )
        trained_days = [r["day"].isoformat() for r in lstm_rows]
    except Exception as exc:
        logger.warning("coverage: lstm days query failed for user %s: %s", user.id, exc)
        trained_days = []

    total_bars = sum(d["bars"] for d in days)

    return {
        "days":         days,
        "trained_days": trained_days,
        "total_bars":   total_bars,
        "total_days":   len(days),
        "instrument":   "MES",
    }


# ── REST: whole-database data inventory (Data page) ──────────────────────────
#
# Unlike /coverage (which filters to live rows only for the settings calendar),
# these endpoints report ALL bar data — live AND training together — with the
# split broken out, so the user can see exactly what is in the DB.
#
# "bars" everywhere means DISTINCT timestamps (bar_type != 'tick'); a session
# replayed in training mode stores duplicate-timestamp rows, so raw row counts
# overstate real coverage. A timestamp can exist as both a live and a training
# row, so live_bars + training_bars may exceed total_bars — that overlap is
# expected and intentional (a day the user both streamed live and re-imported).

# A near-full US equity RTH session is 390 one-minute bars (9:30–16:00 ET).
# We call a day "complete" at >= 370 bars, leaving ~20 bars of slack for the
# open/close auction minutes and the odd dropped bar. Approximate by design.
_COMPLETE_DAY_BARS = 370

# Rough on-disk size per stored row (OHLCV + ids + overhead). Order-of-magnitude
# only — for a "how big is this getting" gut check, not an exact figure.
_BYTES_PER_ROW = 100


async def _timeframe_breakdown(conn, user_id) -> list[dict]:
    """Per-timeframe bar counts across ALL timeframes (for the Data-tab selector)."""
    try:
        rows = await conn.fetch(
            """SELECT timeframe,
                      COUNT(DISTINCT time)                                    AS total_bars,
                      COUNT(DISTINCT time) FILTER (WHERE is_training = false) AS live_bars,
                      COUNT(DISTINCT time) FILTER (WHERE is_training = true)  AS training_bars,
                      COUNT(DISTINCT date_trunc('day', time))                 AS days
               FROM ticks
               WHERE user_id = $1 AND bar_type != 'tick'
               GROUP BY timeframe
               ORDER BY timeframe ASC""",
            user_id,
        )
    except Exception:
        return []
    return [
        {"timeframe": r["timeframe"], "total_bars": r["total_bars"],
         "live_bars": r["live_bars"], "training_bars": r["training_bars"], "days": r["days"]}
        for r in rows
    ]


@router.get("/data-summary")
async def data_summary(
    timeframe: str = "1min",
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> dict:
    """
    Whole-database inventory of this user's bar data (live + training), scoped to
    *timeframe*. Also returns `timeframes`: a per-timeframe breakdown across ALL
    timeframes so the Data tab can show 1-min and 5-min coverage side by side.
    """
    timeframes = await _timeframe_breakdown(conn, user.id)

    try:
        totals = await conn.fetchrow(
            """SELECT
                   COUNT(DISTINCT time)                                       AS total_bars,
                   COUNT(*)                                                   AS total_raw_rows,
                   COUNT(DISTINCT time) FILTER (WHERE is_training = false)     AS live_bars,
                   COUNT(DISTINCT time) FILTER (WHERE is_training = true)      AS training_bars,
                   MIN(time)                                                   AS min_time,
                   MAX(time)                                                   AS max_time
               FROM ticks
               WHERE user_id = $1 AND bar_type != 'tick' AND timeframe = $2""",
            user.id, timeframe,
        )
    except Exception as exc:
        logger.warning("data_summary: totals query failed for user %s: %s", user.id, exc)
        totals = None

    if not totals or (totals["total_raw_rows"] or 0) == 0:
        return {
            "timeframe":          timeframe,
            "timeframes":         timeframes,
            "total_bars":         0,
            "total_raw_rows":     0,
            "live_bars":          0,
            "training_bars":      0,
            "date_range":         {"min": None, "max": None},
            "months":             [],
            "instrument":         None,
            "storage_estimate_mb": 0.0,
            "complete_day_threshold": _COMPLETE_DAY_BARS,
        }

    try:
        month_rows = await conn.fetch(
            """SELECT
                   to_char(date_trunc('month', time), 'YYYY-MM')          AS month,
                   COUNT(DISTINCT time)                                    AS bars,
                   COUNT(DISTINCT date_trunc('day', time))                 AS days,
                   COUNT(DISTINCT time) FILTER (WHERE is_training = false)  AS live_bars,
                   COUNT(DISTINCT time) FILTER (WHERE is_training = true)   AS training_bars
               FROM ticks
               WHERE user_id = $1 AND bar_type != 'tick' AND timeframe = $2
               GROUP BY date_trunc('month', time)
               ORDER BY date_trunc('month', time) ASC""",
            user.id, timeframe,
        )
    except Exception as exc:
        logger.warning("data_summary: months query failed for user %s: %s", user.id, exc)
        month_rows = []

    # Most-common symbol = the instrument (single-instrument system in practice).
    instrument = None
    try:
        sym = await conn.fetchrow(
            """SELECT symbol FROM ticks
               WHERE user_id = $1 AND bar_type != 'tick' AND timeframe = $2
               GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT 1""",
            user.id, timeframe,
        )
        instrument = sym["symbol"] if sym else None
    except Exception:
        instrument = None

    raw_rows = totals["total_raw_rows"] or 0
    return {
        "timeframe":      timeframe,
        "timeframes":     timeframes,
        "total_bars":     totals["total_bars"] or 0,
        "total_raw_rows": raw_rows,
        "live_bars":      totals["live_bars"] or 0,
        "training_bars":  totals["training_bars"] or 0,
        "date_range": {
            "min": totals["min_time"].isoformat() if totals["min_time"] else None,
            "max": totals["max_time"].isoformat() if totals["max_time"] else None,
        },
        "months": [
            {
                "month":         r["month"],
                "bars":          r["bars"],
                "days":          r["days"],
                "live_bars":     r["live_bars"],
                "training_bars": r["training_bars"],
            }
            for r in month_rows
        ],
        "instrument":            instrument,
        "storage_estimate_mb":   round(raw_rows * _BYTES_PER_ROW / (1024 * 1024), 2),
        "complete_day_threshold": _COMPLETE_DAY_BARS,
    }


@router.get("/data-days")
async def data_days(
    month: str,
    timeframe: str = "1min",
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> dict:
    """
    Per-day detail for one month (format YYYY-MM) of *timeframe*. Each day reports
    its distinct bar count, first/last bar time, whether it is "complete"
    (>= 370 bars), and whether the day is live-only, training-only, or mixed.
    """
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise HTTPException(400, "month must be in YYYY-MM format")
    year, mon = int(month[:4]), int(month[5:7])
    if not (1 <= mon <= 12) or not (1970 <= year <= 2100):
        raise HTTPException(400, "month out of range")

    start = datetime(year, mon, 1, tzinfo=timezone.utc)
    end   = datetime(year + (mon // 12), (mon % 12) + 1, 1, tzinfo=timezone.utc)

    try:
        rows = await conn.fetch(
            """SELECT
                   date_trunc('day', time)::date          AS day,
                   COUNT(DISTINCT time)                    AS bars,
                   MIN(time)                               AS first_bar,
                   MAX(time)                               AS last_bar,
                   bool_or(is_training = false)            AS has_live,
                   bool_or(is_training = true)             AS has_training
               FROM ticks
               WHERE user_id = $1
                 AND bar_type != 'tick'
                 AND timeframe = $4
                 AND time >= $2 AND time < $3
               GROUP BY date_trunc('day', time)::date
               ORDER BY day ASC""",
            user.id, start, end, timeframe,
        )
    except Exception as exc:
        logger.warning("data_days: query failed for user %s month %s: %s", user.id, month, exc)
        rows = []

    days = []
    for r in rows:
        has_live, has_training = bool(r["has_live"]), bool(r["has_training"])
        kind = "mixed" if (has_live and has_training) else ("live" if has_live else "training")
        days.append({
            "date":        r["day"].isoformat(),
            "bars":        r["bars"],
            "first_bar":   r["first_bar"].isoformat() if r["first_bar"] else None,
            "last_bar":    r["last_bar"].isoformat() if r["last_bar"] else None,
            "is_complete": r["bars"] >= _COMPLETE_DAY_BARS,
            "kind":        kind,
        })

    return {
        "month":                  month,
        "days":                   days,
        "complete_day_threshold": _COMPLETE_DAY_BARS,
    }


@router.get("/data-integrity")
async def data_integrity(
    timeframe: str = "1min",
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> dict:
    """
    Health check on the stored bar data for *timeframe* so the user can verify a
    big import landed cleanly: complete vs partial days, duplicate-timestamp count
    (should be 0 after dedup), and weekday gaps (weekdays inside the date range
    with zero bars). Live + training combined.

    Duplicate detection is timeframe-scoped — a 1-min and a 5-min bar at the same
    timestamp are DIFFERENT series and must NOT count as duplicates of each other.
    """
    try:
        day_rows = await conn.fetch(
            """SELECT date_trunc('day', time)::date AS day, COUNT(DISTINCT time) AS bars
               FROM ticks
               WHERE user_id = $1 AND bar_type != 'tick' AND timeframe = $2
               GROUP BY date_trunc('day', time)::date
               ORDER BY day ASC""",
            user.id, timeframe,
        )
    except Exception as exc:
        logger.warning("data_integrity: day query failed for user %s: %s", user.id, exc)
        day_rows = []

    try:
        duplicate_timestamps = await conn.fetchval(
            """SELECT COUNT(*) FROM (
                   SELECT time FROM ticks
                   WHERE user_id = $1 AND bar_type != 'tick' AND timeframe = $2
                   GROUP BY time HAVING COUNT(*) > 1
               ) dups""",
            user.id, timeframe,
        ) or 0
    except Exception as exc:
        logger.warning("data_integrity: dup query failed for user %s: %s", user.id, exc)
        duplicate_timestamps = 0

    days_with_bars = {r["day"] for r in day_rows}
    total_days    = len(day_rows)
    complete_days = sum(1 for r in day_rows if r["bars"] >= _COMPLETE_DAY_BARS)
    partial_days  = total_days - complete_days

    # Weekday gaps: any Mon–Fri inside [first, last] that has zero bars.
    missing: list[str] = []
    if day_rows:
        cur, last = day_rows[0]["day"], day_rows[-1]["day"]
        while cur <= last:
            if cur.weekday() < 5 and cur not in days_with_bars:
                missing.append(cur.isoformat())
            cur += timedelta(days=1)

    return {
        "total_days":           total_days,
        "complete_days":        complete_days,
        "partial_days":         partial_days,
        "duplicate_timestamps": int(duplicate_timestamps),
        "missing_weekdays":     {"count": len(missing), "dates": missing[:60]},
        "date_range": {
            "min": day_rows[0]["day"].isoformat()  if day_rows else None,
            "max": day_rows[-1]["day"].isoformat() if day_rows else None,
        },
        "complete_day_threshold": _COMPLETE_DAY_BARS,
    }


# ── REST: gap-fill coverage for the NinjaTrader strategy ─────────────────────
#
# Called by the NinjaScript strategy (which holds the NT token but has no browser
# session) so it can send only the bars the backend is missing, instead of
# re-blasting the whole chart every time. Auth reuses the exact TCP token path:
# SHA-256 lookup + bcrypt verify via _resolve_token. Bad-token attempts are
# rate-limited per client IP (the HTTP analog of the TCP connection's failure cap).
#
# Response is DELIBERATELY plain text (not JSON) so the strategy can parse it with
# trivial string splits — no JSON library in NinjaScript. Format, one line each:
#     <YYYY-MM-DD>,<distinct_bars>,<first_HH:MM>,<last_HH:MM>   (one per day, UTC)
#     LAST,<YYYY-MM-DDTHH:MM:SSZ>                               (max bar time, UTC)
# Days combine live + training — the strategy just needs to know what EXISTS.
# Empty body means no data (fresh DB → the strategy sends everything).

_GAP_AUTH_WINDOW       = 60.0   # seconds
_GAP_AUTH_MAX_FAILURES = 10     # bad-token attempts per IP per window → 429
_gap_auth_failures: dict[str, list[float]] = {}


def _gap_rate_limited(ip: str) -> bool:
    now  = time.monotonic()
    keep = [t for t in _gap_auth_failures.get(ip, []) if now - t < _GAP_AUTH_WINDOW]
    _gap_auth_failures[ip] = keep
    return len(keep) >= _GAP_AUTH_MAX_FAILURES


def _gap_record_failure(ip: str) -> None:
    _gap_auth_failures.setdefault(ip, []).append(time.monotonic())


@router.get("/gaps", response_class=PlainTextResponse)
async def data_gaps(request: Request, token: str = "", tf: str = "1min") -> str:
    """
    NT-token-authenticated coverage summary for gap-fill imports (plain text).

    Accepts the token as `?token=TM-xxx` or an `X-NT-Token` header, and the
    timeframe as `?tf=1min` / `?tf=5min`. Returns one line per day the user has
    bars for IN THAT TIMEFRAME (live + training combined) plus a LAST line with
    the newest bar time — all UTC. A 5-min chart gap-fills against 5-min coverage
    only, never 1-min. See the module note above for format.
    """
    ip = request.client.host if request.client else "unknown"
    if _gap_rate_limited(ip):
        raise HTTPException(429, "Too many bad token attempts — slow down")

    token = (token or request.headers.get("X-NT-Token") or "").strip()
    if not token:
        raise HTTPException(401, "Missing NT token")

    pool  = request.app.state.db_pool
    redis = request.app.state.redis
    user_id = await _resolve_token(token, pool, redis)
    if user_id is None:
        _gap_record_failure(ip)
        raise HTTPException(401, "Invalid NT token")

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT date_trunc('day', time)::date AS day,
                          COUNT(DISTINCT time)          AS bars,
                          MIN(time)                     AS first_bar,
                          MAX(time)                     AS last_bar
                   FROM ticks
                   WHERE user_id = $1 AND bar_type != 'tick' AND timeframe = $2
                   GROUP BY date_trunc('day', time)::date
                   ORDER BY day ASC""",
                _uuid.UUID(user_id), tf,
            )
    except Exception as exc:
        logger.warning("data_gaps: coverage query failed for user %s: %s", user_id, exc)
        rows = []

    lines: list[str] = []
    last_time = None
    for r in rows:
        first = r["first_bar"].astimezone(timezone.utc).strftime("%H:%M") if r["first_bar"] else ""
        last  = r["last_bar"].astimezone(timezone.utc).strftime("%H:%M") if r["last_bar"] else ""
        lines.append(f"{r['day'].isoformat()},{r['bars']},{first},{last}")
        if r["last_bar"] and (last_time is None or r["last_bar"] > last_time):
            last_time = r["last_bar"]

    if last_time is not None:
        lines.append("LAST," + last_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    return "\n".join(lines) + ("\n" if lines else "")


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
