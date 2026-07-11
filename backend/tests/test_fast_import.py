"""
Fast bulk-import path + flush-queue.

Verifies the historical fast path COPYs bars in bulk, still runs in-memory
learning, advances counters, and emits a throttled progress event; that the
consumer router sends hist+training bars to the fast path and everything else to
the normal path; and that flush-queue drops the backlog and clears deferred state.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.services.market_data import ingestion
from app.services.market_data import features
from app.services.market_data.ingestion import (
    _process_hist_batch,
    _route_entries,
    flush_queue,
    start_training,
    training_status,
)


USER = str(uuid.uuid4())
T0 = datetime(2026, 5, 1, 13, 31, tzinfo=timezone.utc)


class FakeConn:
    def __init__(self):
        self.copied = []

    async def copy_records_to_table(self, table, records, columns):
        self.copied.append((table, list(records), columns))

    async def fetch(self, q, *a):
        return []

    async def execute(self, q, *a):
        return "INSERT 0 1"

    async def fetchval(self, q, *a):
        return None

    async def fetchrow(self, q, *a):
        return None


class FakeAcquire:
    def __init__(self, c):
        self._c = c

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *e):
        return False


class FakePool:
    def __init__(self):
        self.conn = FakeConn()

    def acquire(self):
        return FakeAcquire(self.conn)


class FakeRedis:
    def __init__(self, length=0):
        self.published = []
        self._len = length
        self.trimmed = None
        self.pending_cleared = False

    async def publish(self, ch, msg):
        self.published.append((ch, msg))
        return 1

    async def xlen(self, key):
        return self._len

    async def xtrim(self, key, maxlen=None, approximate=True):
        self.trimmed = (maxlen, approximate)

    async def xpending(self, key, group):
        return {"pending": 0}


@pytest.fixture(autouse=True)
def _clean():
    from app.services.ml.pipeline import _pipelines, _pipeline_locks

    def _reset():
        for d in (ingestion._last_bar_time, ingestion._bar_state, ingestion._system_mode,
                  ingestion._training_bar_count, ingestion._training_sessions,
                  ingestion._warmed_engines, ingestion._mode_reject_at):
            d.clear()
        features._engines.clear()
        # Pipeline/lock registries are keyed by (user_id, timeframe, context) — clear all.
        for reg in (_pipelines, _pipeline_locks):
            for k in [k for k in reg if isinstance(k, tuple) and k[0] == USER]:
                reg.pop(k, None)

    _reset()
    yield
    _reset()


def _tick(i):
    price = 5000.0 + (i % 30) * 0.25
    from app.models.tick import Tick
    return Tick(
        time=T0 + timedelta(minutes=i), user_id=uuid.UUID(USER), symbol="MES 09-26",
        open=price, high=price + 1.0, low=price - 1.0, close=price + 0.5,
        volume=100 + (i % 20), bar_type="hist",
    )


@pytest.mark.asyncio
async def test_fast_batch_copies_bars_learns_and_reports_progress():
    start_training(USER)
    pool, redis = FakePool(), FakeRedis(length=7)
    batch = [(f"{i}-0", _tick(i)) for i in range(60)]   # > 50-bar warmup

    await _process_hist_batch(batch, pool, redis)

    # All 60 bars written in a single COPY (one call, 60 records).
    assert len(pool.conn.copied) == 1
    assert len(pool.conn.copied[0][1]) == 60
    # Run counter advanced by 60.
    assert training_status(USER)["bars_ingested"] == 60
    # Symbol from a continuous contract flows through untouched into the records.
    assert pool.conn.copied[0][1][0][2] == "MES 09-26"
    # Learning actually happened (bars past warmup advanced bars_learned).
    # hist bars are OFFLINE training data → the (USER, "1min", "offline") pipeline.
    from app.services.ml.pipeline import _pipelines
    assert _pipelines[(USER, "1min", "offline")].xp_trackers["momentum"].bars_learned > 0
    # Exactly one throttled progress event (not one WS bar per bar).
    prog = [m for _c, m in redis.published if '"training_progress"' in m]
    assert len(prog) == 1
    assert '"queue_pending": 7' in prog[0]


@pytest.mark.asyncio
async def test_router_splits_fast_and_normal(monkeypatch):
    start_training(USER)
    fast = AsyncMock()
    normal = AsyncMock()
    ack = AsyncMock()
    monkeypatch.setattr(ingestion, "_process_hist_batch", fast)
    monkeypatch.setattr(ingestion, "_handle_entry", normal)
    monkeypatch.setattr(ingestion, "_ack", ack)

    def flds(bar_type):
        return {"timestamp": T0.isoformat(), "user_id": USER, "symbol": "MES",
                "open": "1", "high": "2", "low": "1", "close": "1.5",
                "volume": "10", "bar_type": bar_type}

    entries = [("1-0", flds("hist")), ("2-0", flds("1min"))]
    await _route_entries(entries, FakePool(), FakeRedis())

    # hist+training → fast batch (1 hist entry); 1min → normal path.
    assert fast.await_count == 1
    assert len(fast.await_args[0][0]) == 1        # one hist tick batched
    assert normal.await_count == 1                # the 1min bar


@pytest.mark.asyncio
async def test_hist_when_training_off_goes_to_normal_path(monkeypatch):
    # training OFF → hist bar must NOT hit the fast path (normal path rejects it).
    fast = AsyncMock()
    normal = AsyncMock()
    monkeypatch.setattr(ingestion, "_process_hist_batch", fast)
    monkeypatch.setattr(ingestion, "_handle_entry", normal)

    entries = [("1-0", {"timestamp": T0.isoformat(), "user_id": USER, "symbol": "MES",
                        "open": "1", "high": "2", "low": "1", "close": "1.5",
                        "volume": "10", "bar_type": "hist"})]
    await _route_entries(entries, FakePool(), FakeRedis())

    assert fast.await_count == 0
    assert normal.await_count == 1


@pytest.mark.asyncio
async def test_flush_queue_drops_backlog_and_clears_state():
    ingestion._bar_state[(USER, "1min", "live")] = {"features": {}, "predictions": {}, "close": 1.0}
    # A pipeline with a buffered pending trade that must be cleared.
    from app.services.ml.pipeline import MLPipeline, _pipelines
    pl = MLPipeline(USER, {}, timeframe="1min")
    pl._pending_champion = [{"model_name": "momentum"}]
    _pipelines[(USER, "1min", "live")] = pl

    redis = FakeRedis(length=5)
    dropped = await flush_queue(USER, redis)

    assert dropped == 5
    assert redis.trimmed == (0, False)             # XTRIM MAXLEN 0
    assert (USER, "1min") not in ingestion._bar_state   # deferred state cleared
    assert pl._pending_champion == []               # buffered trades cleared
