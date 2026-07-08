"""
Training-mode tests.

Core guarantee: with training mode ON the ingestion pipeline accepts a bar whose
timestamp is OLDER than the live watermark (so historical replay works), while
with training mode OFF that same bar is rejected by the monotonic guard. Training
bars are tagged is_training=true and must NOT advance the live watermark.
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


def _fields(ts):
    return {
        "timestamp": ts.isoformat(),
        "user_id":   USER,
        "symbol":    "MES",
        "open":      "5840", "high": "5841", "low": "5839", "close": "5840.5",
        "volume":    "100",  "bar_type": "1min",
    }


@pytest.fixture(autouse=True)
def _clean_state():
    for d in (
        ingestion._last_bar_time, ingestion._bar_state,
        ingestion._training_mode, ingestion._training_bar_count,
        ingestion._training_sessions,
    ):
        d.clear()
    features._engines.clear()
    yield
    for d in (
        ingestion._last_bar_time, ingestion._bar_state,
        ingestion._training_mode, ingestion._training_bar_count,
        ingestion._training_sessions,
    ):
        d.clear()
    features._engines.clear()


# ── 1. Training OFF — a bar older than the watermark is REJECTED ─────────────

@pytest.mark.asyncio
async def test_stale_bar_rejected_when_training_off():
    ingestion._last_bar_time[USER] = T_LATER   # live watermark already advanced
    pool, redis = _Pool(T_LATER), _Redis()

    await _process_entry(_fields(T_OLDER), pool, redis)

    # The monotonic guard rejects it before anything is written.
    assert pool.conn.ticks_written == []
    # Watermark unchanged.
    assert ingestion._last_bar_time[USER] == T_LATER


# ── 2. Training ON — the SAME stale bar is ACCEPTED and tagged ──────────────

@pytest.mark.asyncio
async def test_stale_bar_accepted_when_training_on():
    ingestion._last_bar_time[USER] = T_LATER
    start_training(USER)
    pool, redis = _Pool(T_LATER), _Redis()

    await _process_entry(_fields(T_OLDER), pool, redis)

    # Accepted despite being older than the watermark.
    assert len(pool.conn.ticks_written) == 1
    # …and tagged as training data. INSERT args end (..., bar_type, is_training,
    # timeframe), so is_training is the second-to-last arg.
    assert pool.conn.ticks_written[0][-2] is True
    assert pool.conn.ticks_written[0][-1] == "1min"   # default timeframe
    # The live watermark is NOT advanced/regressed by training bars.
    assert ingestion._last_bar_time[USER] == T_LATER
    # This-run counters advanced.
    status = training_status(USER)
    assert status["training"] is True
    assert status["bars_ingested"] == 1
    assert status["sessions_ingested"] == 1
