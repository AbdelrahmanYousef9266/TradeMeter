"""
Mode-switch guard: switching modes requires a drained ingestion queue so a switch
can't mix historical and live bars mid-stream. With bars queued the switch is
blocked (409) unless {"flush": true} is passed.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.api.routes.mode import _switch
from app.services.market_data import ingestion


UID = str(uuid.uuid4())


class FakeRedis:
    """Minimal Redis for get_queue_pending + flush_queue."""
    def __init__(self, pending: int):
        self._pending = pending
        self.trimmed = False

    async def xlen(self, key):
        return self._pending

    async def xtrim(self, *a, **k):
        self.trimmed = True
        self._pending = 0

    async def xpending(self, *a, **k):
        return {"pending": 0}


@pytest.fixture(autouse=True)
def _clean():
    for d in (ingestion._system_mode, ingestion._training_bar_count,
              ingestion._training_sessions):
        d.clear()
    yield
    for d in (ingestion._system_mode, ingestion._training_bar_count,
              ingestion._training_sessions):
        d.clear()


@pytest.mark.asyncio
async def test_switch_blocked_when_queue_not_drained():
    redis = FakeRedis(pending=5)
    with pytest.raises(HTTPException) as ei:
        await _switch(UID, ingestion.MODE_OFFLINE, flush=False, redis=redis)
    assert ei.value.status_code == 409
    assert ei.value.detail["queue_pending"] == 5
    # Mode NOT changed — still the default LIVE.
    assert ingestion.get_mode(UID) == ingestion.MODE_LIVE
    assert not redis.trimmed


@pytest.mark.asyncio
async def test_switch_flushes_and_switches_with_flag():
    redis = FakeRedis(pending=5)
    st = await _switch(UID, ingestion.MODE_OFFLINE, flush=True, redis=redis)
    assert st["mode"] == ingestion.MODE_OFFLINE
    assert st["flushed"] == 5
    assert redis.trimmed
    assert ingestion.get_mode(UID) == ingestion.MODE_OFFLINE


@pytest.mark.asyncio
async def test_switch_is_free_when_queue_empty():
    redis = FakeRedis(pending=0)
    st = await _switch(UID, ingestion.MODE_OFFLINE, flush=False, redis=redis)
    assert st["mode"] == ingestion.MODE_OFFLINE
    assert ingestion.get_mode(UID) == ingestion.MODE_OFFLINE
    assert not redis.trimmed   # nothing to flush


@pytest.mark.asyncio
async def test_same_mode_switch_is_noop_even_with_queue():
    # Already LIVE; asking for LIVE must not be blocked by a full queue.
    redis = FakeRedis(pending=99)
    st = await _switch(UID, ingestion.MODE_LIVE, flush=False, redis=redis)
    assert st["mode"] == ingestion.MODE_LIVE
    assert not redis.trimmed
