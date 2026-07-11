"""
User reset logic (audit fix #2): scoped, transactional deletion of one user's
learned state, with raw bars kept by default; plus in-memory state eviction.
"""

import uuid

import pytest

from app.services.user_reset import (
    count_user_data,
    reset_user_data,
    purge_in_memory_state,
    _deleted_count,
)

_TABLES = ["predictions", "cc_history", "model_levels", "model_state", "ticks"]

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


def _table_of(query: str) -> str:
    for t in _TABLES:
        if f"FROM {t}" in query:
            return t
    raise AssertionError(f"no known table in: {query}")


class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class ResetConn:
    """In-memory stand-in for a scoped asyncpg connection."""
    def __init__(self, data):
        self.data = {t: list(rows) for t, rows in data.items()}

    async def fetchval(self, query, *args):
        table, uid = _table_of(query), args[0]
        return sum(1 for r in self.data.get(table, []) if r["user_id"] == uid)

    async def execute(self, query, *args):
        table, uid = _table_of(query), args[0]
        before = len(self.data.get(table, []))
        self.data[table] = [r for r in self.data.get(table, []) if r["user_id"] != uid]
        return f"DELETE {before - len(self.data[table])}"

    def transaction(self):
        return _FakeTx()


def _seed():
    return {
        "predictions":  [{"user_id": USER_A}] * 5 + [{"user_id": USER_B}] * 3,
        "cc_history":   [{"user_id": USER_A}] * 2 + [{"user_id": USER_B}] * 1,
        "model_levels": [{"user_id": USER_A}] * 10 + [{"user_id": USER_B}] * 10,
        "model_state":  [{"user_id": USER_A}] * 10 + [{"user_id": USER_B}] * 10,
        "ticks":        [{"user_id": USER_A}] * 100 + [{"user_id": USER_B}] * 50,
    }


def test_deleted_count_parsing():
    assert _deleted_count("DELETE 42") == 42
    assert _deleted_count("DELETE 0") == 0
    assert _deleted_count("garbage") == 0


@pytest.mark.asyncio
async def test_count_user_data_scoped():
    conn = ResetConn(_seed())
    counts = await count_user_data(conn, USER_A, include_bars=True)
    assert counts == {"predictions": 5, "cc_history": 2, "model_levels": 10,
                      "model_state": 10, "ticks": 100}
    # Without include_bars, ticks are not counted.
    assert "ticks" not in await count_user_data(conn, USER_A, include_bars=False)


@pytest.mark.asyncio
async def test_reset_keeps_bars_by_default():
    conn = ResetConn(_seed())
    deleted = await reset_user_data(conn, USER_A, include_bars=False)

    assert deleted == {"predictions": 5, "cc_history": 2, "model_levels": 10, "model_state": 10}
    # User A learned state gone; user A bars KEPT.
    assert all(r["user_id"] != USER_A for r in conn.data["model_state"])
    assert sum(r["user_id"] == USER_A for r in conn.data["ticks"]) == 100
    # User B is entirely untouched.
    assert sum(r["user_id"] == USER_B for r in conn.data["predictions"]) == 3
    assert sum(r["user_id"] == USER_B for r in conn.data["model_state"]) == 10


@pytest.mark.asyncio
async def test_reset_include_bars_wipes_ticks():
    conn = ResetConn(_seed())
    deleted = await reset_user_data(conn, USER_A, include_bars=True)

    assert deleted["ticks"] == 100
    assert all(r["user_id"] != USER_A for r in conn.data["ticks"])
    # User B bars survive.
    assert sum(r["user_id"] == USER_B for r in conn.data["ticks"]) == 50


def test_purge_in_memory_state_evicts_only_target_user():
    from app.services.ml.pipeline import _pipelines, _pipeline_locks
    from app.services.market_data.features import _engines
    from app.services.market_data import ingestion as ing

    a, b = "user-a", "user-b"

    # Phase 2 keys the pipeline/engine/bar-state/watermark registries by
    # (user_id, timeframe) — the purge must clear EVERY timeframe for the target
    # user, so seed both 1-min and 5-min entries here.
    tuple_registries = [_pipelines, _pipeline_locks, _engines,
                        ing._bar_state, ing._last_bar_time]
    # These stay keyed by the plain str(user_id).
    str_registries = [ing._training_mode, ing._training_bar_count,
                      ing._training_sessions]

    for reg in tuple_registries:
        for tf in ("1min", "5min"):
            reg[(a, tf)] = "sentinel-a"
            reg[(b, tf)] = "sentinel-b"
    for reg in str_registries:
        reg[a] = "sentinel-a"
        reg[b] = "sentinel-b"

    try:
        purge_in_memory_state(a)
        for reg in tuple_registries:
            assert (a, "1min") not in reg and (a, "5min") not in reg, \
                "every timeframe for the target user must be evicted"
            assert reg[(b, "1min")] == "sentinel-b" and reg[(b, "5min")] == "sentinel-b", \
                "other users must be preserved"
        for reg in str_registries:
            assert a not in reg, "target user must be evicted"
            assert reg[b] == "sentinel-b", "other users must be preserved"
    finally:
        for reg in tuple_registries:
            for tf in ("1min", "5min"):
                reg.pop((a, tf), None)
                reg.pop((b, tf), None)
        for reg in str_registries:
            reg.pop(a, None)
            reg.pop(b, None)


def test_purge_missing_user_is_noop():
    # Must not raise for a user with no in-memory state.
    purge_in_memory_state(str(uuid.uuid4()))
