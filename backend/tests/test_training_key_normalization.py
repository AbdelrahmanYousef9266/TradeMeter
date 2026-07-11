"""
Regression: the training registries must be immune to key-form mismatch.

start_training / is_training_mode / training_status all canonicalize the key to
str(user_id) internally, so a caller using a uuid.UUID and a caller using its
string form address the SAME entry. This guards the class of bug where the API
sets the flag under one key form and the ingestion consumer reads it under
another — the historical-import gate would then wrongly reject bars.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.services.market_data import ingestion
from app.services.market_data import features
from app.services.market_data.ingestion import (
    _process_entry,
    start_training,
    stop_training,
    is_training_mode,
    training_status,
)


UID = uuid.uuid4()
T = datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_state():
    regs = (
        ingestion._last_bar_time, ingestion._bar_state,
        ingestion._system_mode, ingestion._training_bar_count,
        ingestion._training_sessions, ingestion._hist_reject_warn_at,
    )
    for d in regs:
        d.clear()
    features._engines.clear()
    yield
    for d in regs:
        d.clear()
    features._engines.clear()


# ── Unit: UUID in, string out (and vice versa) ──────────────────────────────

def test_start_with_uuid_read_with_string():
    start_training(UID)                       # UUID object
    assert is_training_mode(str(UID)) is True # string form
    assert training_status(str(UID))["training"] is True


def test_start_with_string_read_with_uuid():
    start_training(str(UID))                   # string form
    assert is_training_mode(UID) is True        # UUID object
    assert training_status(UID)["training"] is True


def test_stop_is_key_normalized_too():
    start_training(str(UID))
    stop_training(UID)                          # stop via the other form
    assert is_training_mode(str(UID)) is False


def test_registry_has_exactly_one_key_form():
    start_training(UID)
    # Only the canonical string key exists — no stray UUID-object key.
    assert set(ingestion._system_mode.keys()) == {str(UID)}
    assert all(isinstance(k, str) for k in ingestion._system_mode)


# ── Integration: hist bar accepted across differing key forms end-to-end ─────

class _Conn:
    def __init__(self):
        self.ticks_written = []

    async def fetchval(self, q, *a):
        return None

    async def execute(self, q, *a):
        if "INTO ticks" in q:
            self.ticks_written.append(a)
        return None

    async def fetch(self, q, *a):
        return []

    async def fetchrow(self, q, *a):
        return None


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *e):
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
        "user_id":   str(UID),
        "symbol":    "MES",
        "open": "5840", "high": "5841", "low": "5839", "close": "5840.5",
        "volume": "100", "bar_type": "hist",
    }


@pytest.mark.asyncio
async def test_hist_bar_accepted_when_training_started_with_uuid_object():
    # Training started under a uuid.UUID key (the exact mismatch scenario);
    # ingestion parses the stream user_id to UUID then keys by str(...). The
    # gate must still see training as ON and accept + tag the bar.
    start_training(UID)                      # UUID object, not str
    pool, redis = _Pool(), _Redis()

    await _process_entry(_hist_fields(), pool, redis)

    assert len(pool.conn.ticks_written) == 1
    assert pool.conn.ticks_written[0][-2] is True   # tagged is_training (timeframe is now last)
    # And the run counter advanced under the same canonical key.
    assert training_status(str(UID))["bars_ingested"] == 1
