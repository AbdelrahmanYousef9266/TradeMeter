"""
Multi-timeframe data-layer isolation (Phase 1).

Proves 1-min and 5-min bars are fully independent series: the watermark is
per-timeframe, same-timestamp bars of different timeframes both persist (no false
dedup), the gaps endpoint is timeframe-scoped (5-min gap-fill ignores 1-min), and
data-summary exposes a per-timeframe breakdown.
"""

import uuid
from datetime import datetime, date, timezone
from types import SimpleNamespace

import pytest

from app.services.market_data import ingestion, features
from app.services.market_data.ingestion import _accept_bar, _process_hist_batch, start_training
from app.api.routes import market
from app.api.routes.market import data_gaps, data_summary


USER = str(uuid.uuid4())
T0 = datetime(2026, 6, 5, 14, 30, tzinfo=timezone.utc)


# ── Shared fakes ─────────────────────────────────────────────────────────────

class _Conn:
    def __init__(self, watermark=None):
        self._wm = watermark
        self.copied = []

    async def fetchval(self, q, *a):
        return self._wm

    async def copy_records_to_table(self, table, records, columns):
        self.copied.append((table, list(records), columns))

    async def fetch(self, q, *a):
        return []

    async def execute(self, q, *a):
        return "OK"

    async def fetchrow(self, q, *a):
        return None


class _Acquire:
    def __init__(self, c):
        self._c = c

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *e):
        return False


class _Pool:
    def __init__(self, watermark=None):
        self.conn = _Conn(watermark)

    def acquire(self):
        return _Acquire(self.conn)


class _Redis:
    async def publish(self, ch, msg):
        return 1

    async def xlen(self, k):
        return 0


@pytest.fixture(autouse=True)
def _clean():
    for d in (ingestion._last_bar_time, ingestion._bar_state, ingestion._system_mode,
              ingestion._training_bar_count, ingestion._training_sessions,
              ingestion._warmed_engines, ingestion._mode_reject_at):
        d.clear()
    features._engines.clear()
    from app.services.ml.pipeline import _pipelines, _pipeline_locks
    _pipelines.pop(USER, None); _pipeline_locks.pop(USER, None)
    yield
    for d in (ingestion._last_bar_time, ingestion._bar_state, ingestion._system_mode,
              ingestion._training_bar_count, ingestion._training_sessions,
              ingestion._warmed_engines, ingestion._mode_reject_at):
        d.clear()
    features._engines.clear()
    _pipelines.pop(USER, None); _pipeline_locks.pop(USER, None)


# ── 1. Watermark is per (user, timeframe) ────────────────────────────────────

@pytest.mark.asyncio
async def test_watermark_is_timeframe_scoped():
    pool = _Pool(watermark=None)
    # A 1-min bar at T0 is accepted.
    assert await _accept_bar(USER, "1min", T0, pool) is True
    # A 5-min bar at the SAME timestamp is a different series → also accepted.
    assert await _accept_bar(USER, "5min", T0, pool) is True
    # Each dedups only within its own timeframe.
    assert await _accept_bar(USER, "1min", T0, pool) is False
    assert await _accept_bar(USER, "5min", T0, pool) is False
    # Distinct watermark keys exist (per (user, timeframe, context)).
    assert (USER, "1min", "live") in ingestion._last_bar_time
    assert (USER, "5min", "live") in ingestion._last_bar_time


# ── 2. Same-timestamp bars of different timeframes both persist (COPY) ───────

def _tick(tf, i=0):
    from app.models.tick import Tick
    p = 5000.0 + i * 0.25
    return Tick(time=T0, user_id=uuid.UUID(USER), symbol="MES 09-26",
                open=p, high=p + 1, low=p - 1, close=p + 0.5, volume=100,
                bar_type="hist", timeframe=tf)


@pytest.mark.asyncio
async def test_same_timestamp_different_timeframe_both_stored():
    start_training(USER)
    pool, redis = _Pool(), _Redis()
    batch = [("1-0", _tick("1min")), ("2-0", _tick("5min"))]

    await _process_hist_batch(batch, pool, redis)

    records = pool.conn.copied[0][1]
    assert len(records) == 2                       # both rows written, no dedup
    assert records[0][0] == records[1][0] == T0    # identical timestamp
    assert {r[-1] for r in records} == {"1min", "5min"}   # timeframe is the last column


# ── 3. Gaps endpoint is timeframe-scoped ─────────────────────────────────────

class _GapsConn:
    def __init__(self):
        self.tf_seen = None

    async def fetch(self, q, *a):
        self.tf_seen = a[1]   # data_gaps passes (uuid, tf)
        bars = 78 if a[1] == "5min" else 390       # a 5-min RTH day ≈ 78 bars
        return [{"day": date(2026, 6, 5), "bars": bars,
                 "first_bar": datetime(2026, 6, 5, 13, 31, tzinfo=timezone.utc),
                 "last_bar": datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc)}]


class _GapsPool:
    def __init__(self, conn):
        self._c = conn

    def acquire(self):
        return _Acquire(self._c)


def _gap_request(pool):
    app = SimpleNamespace(state=SimpleNamespace(db_pool=pool, redis=object()))
    return SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"),
                           headers={}, app=app)


@pytest.mark.asyncio
async def test_gaps_endpoint_timeframe_scoped(monkeypatch):
    async def fake_resolve(token, pool, redis):
        return USER
    monkeypatch.setattr(market, "_resolve_token", fake_resolve)
    market._gap_auth_failures.clear()

    conn = _GapsConn()
    out = await data_gaps(_gap_request(_GapsPool(conn)), token="TM-ABC", tf="5min")

    assert conn.tf_seen == "5min"                  # query filtered by 5min
    assert "2026-06-05,78," in out                 # 5-min coverage, NOT the 1-min 390
    assert ",390," not in out


# ── 4. data-summary per-timeframe breakdown ──────────────────────────────────

class _SummaryConn:
    async def fetch(self, q, *a):
        if "GROUP BY timeframe" in q:
            return [
                {"timeframe": "1min", "total_bars": 390, "live_bars": 390, "training_bars": 0, "days": 1},
                {"timeframe": "5min", "total_bars": 78,  "live_bars": 0,   "training_bars": 78, "days": 1},
            ]
        if "date_trunc('month'" in q:
            return [{"month": "2026-06", "bars": 390, "days": 1, "live_bars": 390, "training_bars": 0}]
        return []

    async def fetchrow(self, q, *a):
        if "MIN(time)" in q:      # scoped totals (timeframe is $2)
            assert a[1] == "1min"
            return {"total_bars": 390, "total_raw_rows": 390, "live_bars": 390, "training_bars": 0,
                    "min_time": datetime(2026, 6, 5, 13, 31, tzinfo=timezone.utc),
                    "max_time": datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc)}
        if "GROUP BY symbol" in q:
            return {"symbol": "MES 09-26"}
        return None


@pytest.mark.asyncio
async def test_data_summary_timeframe_breakdown():
    user = SimpleNamespace(id=uuid.uuid4())
    out = await data_summary(timeframe="1min", user=user, conn=_SummaryConn())

    assert out["timeframe"] == "1min"
    assert out["total_bars"] == 390                # scoped to 1min
    # Breakdown exposes BOTH timeframes for the selector.
    by = {t["timeframe"]: t["total_bars"] for t in out["timeframes"]}
    assert by == {"1min": 390, "5min": 78}
