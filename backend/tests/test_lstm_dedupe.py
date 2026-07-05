"""
LSTM training deduplication (audit fix #9).

Replaying the same session in training mode inserts duplicate-timestamp bars.
The trainer must count each timestamp once and build sequences from a series
with no duplicate timestamps (preferring the live row over a training copy),
so a repeated replay can't inflate the activation gate or bias the LSTM.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.ml.lstm_trainer import count_available_bars, build_training_data
from app.services.ml.lstm_model import MIN_BARS_TO_ACTIVATE

_UID = str(uuid.uuid4())


class FakeConn:
    """
    Emulates just the two dedup queries the trainer issues against Postgres:
      COUNT(DISTINCT time)              → distinct-timestamp count
      SELECT DISTINCT ON (time) ...     → one row per timestamp, live preferred
                                          (ORDER BY time ASC, is_training ASC)
    """
    def __init__(self, bars):
        self.bars = bars
        self.last_fetch = None

    async def fetchrow(self, query, *args):
        if "COUNT(DISTINCT time)" in query:
            times = {b["time"] for b in self.bars if b["bar_type"] != "tick"}
            return {"n": len(times)}
        raise AssertionError(f"unexpected fetchrow: {query}")

    async def fetch(self, query, *args):
        assert "DISTINCT ON (time)" in query, f"trainer must dedup by timestamp: {query}"
        assert "is_training ASC" in query, "must prefer the live row on ties"
        best = {}
        for b in self.bars:
            if b["bar_type"] == "tick":
                continue
            t = b["time"]
            cur = best.get(t)
            if cur is None or b["is_training"] < cur["is_training"]:
                best[t] = b
        rows = [best[t] for t in sorted(best)]
        self.last_fetch = rows
        return rows


def _duplicated_session(n_bars):
    """
    n_bars distinct timestamps, each present TWICE: a training copy (inserted
    first, with a clearly different price) and a live copy. Dedup must keep the
    live copy regardless of insertion order.
    """
    base = datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc)
    bars = []
    for i in range(n_bars):
        t = base + timedelta(minutes=i)
        price = 5000.0 + (i % 40) * 0.25
        training = {"time": t, "open": price + 500, "high": price + 501, "low": price + 499,
                    "close": price + 500.5, "volume": 200, "bar_type": "1min", "is_training": True}
        live = {"time": t, "open": price, "high": price + 1.0, "low": price - 1.0,
                "close": price + 0.5, "volume": 100 + (i % 20), "bar_type": "1min", "is_training": False}
        bars.append(training)   # training inserted BEFORE live on purpose
        bars.append(live)
    return bars


@pytest.mark.asyncio
async def test_count_available_bars_counts_each_timestamp_once():
    bars = _duplicated_session(60)          # 60 distinct times, 120 raw rows
    conn = FakeConn(bars)
    n = await count_available_bars(conn, _UID)
    assert n == 60, f"expected 60 distinct timestamps, got {n}"


@pytest.mark.asyncio
async def test_build_training_data_dedupes_by_timestamp():
    n_bars = MIN_BARS_TO_ACTIVATE + 100     # comfortably over the gate
    bars = _duplicated_session(n_bars)      # 2× raw rows
    conn = FakeConn(bars)

    result = await build_training_data(conn, _UID)
    assert result is not None, "should have enough deduped bars to train"

    series = conn.last_fetch
    times = [r["time"] for r in series]
    # Exactly one row per timestamp, strictly increasing, no duplicates.
    assert len(times) == n_bars
    assert len(set(times)) == n_bars
    assert times == sorted(times)
    # The live row (is_training=False) was kept on every tie.
    assert all(r["is_training"] is False for r in series)
    # And its price, not the +500 training copy's, is what feeds training.
    assert all(r["close"] < 5100 for r in series)


@pytest.mark.asyncio
async def test_duplicate_replays_do_not_inflate_gate():
    """A session replayed below the gate must NOT trip activation via copies."""
    half = MIN_BARS_TO_ACTIVATE // 2
    bars = _duplicated_session(half)        # half distinct times, but 2× raw rows
    conn = FakeConn(bars)

    # Raw row count (2×half) would clear the gate; distinct count must not.
    assert len(bars) >= MIN_BARS_TO_ACTIVATE
    n = await count_available_bars(conn, _UID)
    assert n == half
    assert await build_training_data(conn, _UID) is None
