"""
Idempotency / monotonic-order guard tests (#3).

_accept_bar() returns True only for a strictly-newer bar timestamp, so a
consumer-group redelivery (at-least-once) or an out-of-order replay applies
durable effects exactly once.  The high-water mark seeds from the ticks table
so it survives a restart.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.market_data import ingestion
from app.services.market_data.ingestion import _accept_bar


USER = "55555555-5555-5555-5555-555555555555"
T0 = datetime(2026, 6, 29, 14, 30, tzinfo=timezone.utc)


# ── Fake asyncpg pool whose MAX(time) query returns a preset watermark ───────

class _FakeConn:
    def __init__(self, max_time):
        self._max = max_time

    async def fetchval(self, query, *args):
        return self._max


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, max_time=None):
        self._conn = _FakeConn(max_time)

    def acquire(self):
        return _FakeAcquire(self._conn)


@pytest.fixture(autouse=True)
def _clear_watermarks():
    ingestion._last_bar_time.clear()
    yield
    ingestion._last_bar_time.clear()


# ── 1. Brand-new user (no ticks) — first bar accepted, then dedup kicks in ───

@pytest.mark.asyncio
async def test_first_bar_accepted_for_new_user():
    pool = _FakePool(max_time=None)
    assert await _accept_bar(USER, T0, pool) is True
    # Same timestamp again → duplicate → skipped
    assert await _accept_bar(USER, T0, pool) is False


# ── 2. Strictly newer bars are accepted; equal/older are skipped ─────────────

@pytest.mark.asyncio
async def test_monotonic_acceptance():
    pool = _FakePool(max_time=None)
    assert await _accept_bar(USER, T0, pool) is True
    assert await _accept_bar(USER, T0 + timedelta(minutes=1), pool) is True   # newer
    assert await _accept_bar(USER, T0 + timedelta(minutes=1), pool) is False  # duplicate
    assert await _accept_bar(USER, T0, pool) is False                          # out of order
    assert await _accept_bar(USER, T0 + timedelta(minutes=2), pool) is True   # newer again


# ── 3. Watermark seeded from DB survives a "restart" ─────────────────────────

@pytest.mark.asyncio
async def test_watermark_seeded_from_db_blocks_replay():
    # Simulate restart: in-memory empty, but ticks table already has bars up to T0+5m
    seeded = T0 + timedelta(minutes=5)
    pool = _FakePool(max_time=seeded)

    # A redelivered bar at or before the seeded watermark is skipped
    assert await _accept_bar(USER, T0 + timedelta(minutes=3), pool) is False
    assert await _accept_bar(USER, seeded, pool) is False
    # Only a genuinely newer bar gets through
    assert await _accept_bar(USER, seeded + timedelta(minutes=1), pool) is True


# ── 4. Seed query failure is non-fatal — falls back to accept-all ────────────

@pytest.mark.asyncio
async def test_seed_failure_is_non_fatal():
    class _BrokenPool:
        def acquire(self):
            raise RuntimeError("pool down")

    # Should not raise; with no watermark it accepts the first bar
    assert await _accept_bar(USER, T0, _BrokenPool()) is True
    # And still dedups within the run afterwards
    assert await _accept_bar(USER, T0, _BrokenPool()) is False
