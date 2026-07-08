"""
Historical bulk-import gate.

Bars sent by the NinjaTrader strategy with bar_type "hist" (the SendHistorical
blast) are a bar close like any other, but must ONLY be ingested while training
mode is ON — otherwise a stray import would pollute live data and fight the
monotonic watermark. When accepted, hist bars follow the training path and are
tagged is_training=true.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.services.market_data import ingestion
from app.services.market_data import features
from app.services.market_data.ingestion import _process_entry, start_training


USER = str(uuid.uuid4())
T = datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)


class _Conn:
    def __init__(self):
        self.ticks_written = []

    async def fetchval(self, query, *args):
        return None

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
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        return _Acquire(self.conn)


class _Redis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, message):
        self.published.append((channel, message))
        return 1


def _hist_fields():
    return {
        "timestamp": T.isoformat(),
        "user_id":   USER,
        "symbol":    "MES",
        "open":      "5840", "high": "5841", "low": "5839", "close": "5840.5",
        "volume":    "100",  "bar_type": "hist",
    }


@pytest.fixture(autouse=True)
def _clean_state():
    regs = (
        ingestion._last_bar_time, ingestion._bar_state,
        ingestion._training_mode, ingestion._training_bar_count,
        ingestion._training_sessions, ingestion._hist_reject_warn_at,
    )
    for d in regs:
        d.clear()
    features._engines.clear()
    yield
    for d in regs:
        d.clear()
    features._engines.clear()


@pytest.mark.asyncio
async def test_hist_bar_rejected_when_training_off():
    pool, redis = _Pool(), _Redis()

    await _process_entry(_hist_fields(), pool, redis)

    # Nothing written, nothing published — the bar was dropped at the gate.
    assert pool.conn.ticks_written == []
    assert redis.published == []


@pytest.mark.asyncio
async def test_hist_bar_accepted_and_tagged_when_training_on():
    start_training(USER)
    pool, redis = _Pool(), _Redis()

    await _process_entry(_hist_fields(), pool, redis)

    assert len(pool.conn.ticks_written) == 1
    args = pool.conn.ticks_written[0]
    # INSERT args end (..., bar_type, is_training, timeframe).
    assert args[-3] == "hist"     # bar_type preserved
    assert args[-2] is True       # tagged as training data
    assert args[-1] == "1min"     # default timeframe


@pytest.mark.asyncio
async def test_hist_reject_warning_is_rate_limited(monkeypatch):
    """A 23k-bar blast with training off must not emit 23k warning logs."""
    calls = []
    monkeypatch.setattr(ingestion.logger, "warning", lambda *a, **k: calls.append(a))

    pool, redis = _Pool(), _Redis()
    for _ in range(100):
        await _process_entry(_hist_fields(), pool, redis)

    # Throttled to a single warning for the burst (same user, within interval).
    assert len(calls) == 1
    assert pool.conn.ticks_written == []
