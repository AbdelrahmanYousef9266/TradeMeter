"""
Ingestion consumer-group tests.

Verify the reliability properties that consumer groups give us:
  - pending (delivered-but-unacked) entries from a prior crash are reprocessed
  - every processed entry is ACK'd, even when processing raises (no poison pill)
  - group creation is idempotent (BUSYGROUP is swallowed)

A FakeRedis simulates just enough of the Redis Streams consumer-group API.
_process_entry is patched to a recorder so no DB/Redis I/O is needed.
"""

from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ResponseError

from app.services.market_data import ingestion
from app.services.market_data.ingestion import (
    _drain_pending,
    _ensure_group,
    _handle_entry,
    _GROUP_NAME,
    _CONSUMER_NAME,
    _STREAM_KEY,
)


class FakeRedis:
    """Minimal Redis Streams consumer-group stand-in (single stream, single consumer)."""

    def __init__(self, new=None, pending=None, group_exists=False):
        self.new     = list(new or [])       # (id, fields) not yet delivered to any consumer
        self.pending = list(pending or [])   # (id, fields) delivered to this consumer, unacked
        self.acked   = []                    # ids that were XACK'd
        self.group_exists = group_exists

    async def xgroup_create(self, stream, group, id="$", mkstream=False):
        if self.group_exists:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.group_exists = True

    async def xreadgroup(self, group, consumer, streams, count=None, block=None):
        key, last_id = next(iter(streams.items()))
        if last_id == "0":
            # Pending-entries list for this consumer
            return [[key, list(self.pending)]] if self.pending else []
        # ">" — deliver new messages, move them into the pending list
        if not self.new:
            return []
        batch = self.new[: (count or len(self.new))]
        self.new = self.new[len(batch):]
        self.pending.extend(batch)
        return [[key, batch]]

    async def xack(self, stream, group, entry_id):
        self.acked.append(entry_id)
        self.pending = [(i, f) for (i, f) in self.pending if i != entry_id]
        return 1


# ── 1. Pending entries from a prior crash are reprocessed and acked ──────────

@pytest.mark.asyncio
async def test_drain_pending_reprocesses_and_acks(monkeypatch):
    recorder = AsyncMock()
    monkeypatch.setattr(ingestion, "_process_entry", recorder)

    fr = FakeRedis(pending=[
        ("1-0", {"close": "5840"}),
        ("2-0", {"close": "5841"}),
    ], group_exists=True)

    await _drain_pending(fr, db_pool=None)

    assert recorder.await_count == 2           # both pending entries reprocessed
    assert fr.acked == ["1-0", "2-0"]          # and acked
    assert fr.pending == []                     # PEL drained


@pytest.mark.asyncio
async def test_drain_pending_noop_when_empty(monkeypatch):
    recorder = AsyncMock()
    monkeypatch.setattr(ingestion, "_process_entry", recorder)

    fr = FakeRedis(group_exists=True)
    await _drain_pending(fr, db_pool=None)

    assert recorder.await_count == 0
    assert fr.acked == []


# ── 2. Entry is ACK'd even when processing raises (no poison-pill loop) ──────

@pytest.mark.asyncio
async def test_handle_entry_acks_on_processing_error(monkeypatch):
    boom = AsyncMock(side_effect=RuntimeError("kaboom"))
    monkeypatch.setattr(ingestion, "_process_entry", boom)

    fr = FakeRedis(pending=[("9-0", {"bad": "data"})], group_exists=True)

    await _handle_entry("9-0", {"bad": "data"}, db_pool=None, redis_client=fr)

    assert boom.await_count == 1
    assert fr.acked == ["9-0"]   # acked despite the exception


@pytest.mark.asyncio
async def test_handle_entry_acks_on_success(monkeypatch):
    ok = AsyncMock()
    monkeypatch.setattr(ingestion, "_process_entry", ok)

    fr = FakeRedis(group_exists=True)
    await _handle_entry("3-0", {"close": "5842"}, db_pool=None, redis_client=fr)

    assert ok.await_count == 1
    assert fr.acked == ["3-0"]


# ── 3. Group creation is idempotent ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_group_creates_when_absent():
    fr = FakeRedis(group_exists=False)
    await _ensure_group(fr)
    assert fr.group_exists is True


@pytest.mark.asyncio
async def test_ensure_group_idempotent_on_busygroup():
    fr = FakeRedis(group_exists=True)
    # Must not raise — BUSYGROUP is expected and swallowed
    await _ensure_group(fr)


@pytest.mark.asyncio
async def test_ensure_group_reraises_other_errors():
    class BrokenRedis(FakeRedis):
        async def xgroup_create(self, *a, **k):
            raise ResponseError("ERR some other failure")

    with pytest.raises(ResponseError):
        await _ensure_group(BrokenRedis())
