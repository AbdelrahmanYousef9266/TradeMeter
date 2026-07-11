"""
Mode / watermark tests (OFFLINE == the old training mode).

Core guarantee: in LIVE mode a live bar whose timestamp is OLDER than the
watermark is rejected by the monotonic guard; switching to OFFLINE mode lets a
historical ("hist") bar through regardless of the watermark. Offline bars are
tagged is_training=true and must NOT advance the live watermark.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.services.market_data import ingestion
from app.services.market_data import features
from app.services.market_data.ingestion import (
    _process_entry,
    start_training,
    training_status,
)


USER    = str(uuid.uuid4())
T_LATER = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)   # live watermark
T_OLDER = datetime(2026, 6, 29, 14, 0, tzinfo=timezone.utc)   # BEFORE the watermark


# ── Fakes ────────────────────────────────────────────────────────────────────

class _Conn:
    def __init__(self, watermark):
        self._wm = watermark
        self.ticks_written = []

    async def fetchval(self, query, *args):
        return self._wm

    async def execute(self, query, *args):
        if "INTO ticks" in query:
            self.ticks_written.append(args)   # (..., bar_type, is_training)
        return None

    async def fetch(self, query, *args):
        return []

    async def fetchrow(self, query, *args):
        return None


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, watermark):
        self.conn = _Conn(watermark)

    def acquire(self):
        return _Acquire(self.conn)


class _Redis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, message):
        self.published.append((channel, message))
        return 1


def _fields(ts, bar_type="1min"):
    return {
        "timestamp": ts.isoformat(),
        "user_id":   USER,
        "symbol":    "MES",
        "open":      "5840", "high": "5841", "low": "5839", "close": "5840.5",
        "volume":    "100",  "bar_type": bar_type,
    }


@pytest.fixture(autouse=True)
def _clean_state():
    regs = (
        ingestion._last_bar_time, ingestion._bar_state,
        ingestion._system_mode, ingestion._training_bar_count,
        ingestion._training_sessions, ingestion._warmed_engines,
        ingestion._mode_reject_at,
    )
    for d in regs:
        d.clear()
    features._engines.clear()
    yield
    for d in regs:
        d.clear()
    features._engines.clear()


_WM_KEY = (USER, "1min", "live")   # live watermark for the 1-min series


# ── 1. LIVE mode — a live bar older than the watermark is REJECTED ──────────

@pytest.mark.asyncio
async def test_stale_live_bar_rejected_in_live_mode():
    ingestion._last_bar_time[_WM_KEY] = T_LATER   # live watermark already advanced
    pool, redis = _Pool(T_LATER), _Redis()

    await _process_entry(_fields(T_OLDER), pool, redis)   # default LIVE mode

    # The monotonic guard rejects it before anything is written.
    assert pool.conn.ticks_written == []
    # Watermark unchanged.
    assert ingestion._last_bar_time[_WM_KEY] == T_LATER


# ── 2. OFFLINE mode — a stale HIST bar is ACCEPTED and tagged ───────────────

@pytest.mark.asyncio
async def test_stale_hist_bar_accepted_in_offline_mode():
    ingestion._last_bar_time[_WM_KEY] = T_LATER
    start_training(USER)                          # → OFFLINE mode
    pool, redis = _Pool(T_LATER), _Redis()

    await _process_entry(_fields(T_OLDER, bar_type="hist"), pool, redis)

    # Accepted despite being older than the live watermark.
    assert len(pool.conn.ticks_written) == 1
    # …and tagged as training data. INSERT args end (..., bar_type, is_training,
    # timeframe), so is_training is the second-to-last arg.
    assert pool.conn.ticks_written[0][-2] is True
    assert pool.conn.ticks_written[0][-1] == "1min"   # default timeframe
    # The live watermark is NOT advanced/regressed by offline bars.
    assert ingestion._last_bar_time[_WM_KEY] == T_LATER
    # This-run counters advanced.
    status = training_status(USER)
    assert status["training"] is True
    assert status["bars_ingested"] == 1
    assert status["sessions_ingested"] == 1


# ── 3. OFFLINE mode — a live (non-hist) bar is REFUSED at the gate ──────────

@pytest.mark.asyncio
async def test_live_bar_refused_in_offline_mode():
    start_training(USER)                          # → OFFLINE mode
    pool, redis = _Pool(None), _Redis()

    await _process_entry(_fields(T_LATER, bar_type="1min"), pool, redis)

    # Wrong kind of bar for the mode — dropped, nothing stored.
    assert pool.conn.ticks_written == []
