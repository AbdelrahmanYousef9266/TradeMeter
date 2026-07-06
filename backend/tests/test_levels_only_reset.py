"""
Levels-only reset: delete just the XP/level ladder, keep learned weights.

Two guarantees:
  1. reset_levels_only touches ONLY model_levels (never weights/ticks/etc.).
  2. get_pipeline handles "weights exist but no level rows" cleanly — XP trackers
     start at level 1 (new-user defaults) while River weights restore from
     model_state. This is exactly the post-levels-only-reset state.
"""

import pickle
import uuid

import pytest

from app.services.user_reset import count_levels, reset_levels_only
from app.services.ml import pipeline as pipeline_mod
from app.services.ml.pipeline import MLPipeline, get_pipeline, _pipelines, _pipeline_locks


USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


# ── 1. reset_levels_only deletes only model_levels ──────────────────────────

class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class LevelsConn:
    def __init__(self, rows):
        self.rows = list(rows)   # [{"user_id": ...}]

    async def fetchval(self, q, *a):
        assert "model_levels" in q, "levels-only must only read model_levels"
        uid = a[0]
        return sum(1 for r in self.rows if r["user_id"] == uid)

    async def execute(self, q, *a):
        assert "DELETE FROM model_levels" in q, "levels-only must delete ONLY model_levels"
        uid = a[0]
        before = len(self.rows)
        self.rows = [r for r in self.rows if r["user_id"] != uid]
        return f"DELETE {before - len(self.rows)}"

    def transaction(self):
        return _Tx()


@pytest.mark.asyncio
async def test_reset_levels_only_scoped_and_isolated():
    conn = LevelsConn([{"user_id": USER_A}] * 5 + [{"user_id": USER_B}] * 3)

    assert await count_levels(conn, USER_A) == 5
    deleted = await reset_levels_only(conn, USER_A)

    assert deleted == 5
    # User B's level rows survive; only model_levels was ever touched (asserted
    # inside the fake's execute()).
    assert await count_levels(conn, USER_B) == 3
    assert await count_levels(conn, USER_A) == 0


# ── 2. get_pipeline: weights present, no level rows → level 1 + weights ──────

class PipelineConn:
    """Serves empty model_levels but a real pickled weight blob for model_state."""
    def __init__(self, state_rows):
        self._state_rows = state_rows

    async def fetch(self, q, *a):
        if "FROM model_levels" in q:
            return []                     # levels-only reset wiped these
        if "FROM model_state" in q:
            return self._state_rows       # weights still here
        raise AssertionError(f"unexpected query: {q}")


@pytest.mark.asyncio
async def test_get_pipeline_defaults_levels_but_restores_weights():
    uid = str(uuid.uuid4())
    _pipelines.pop(uid, None)
    _pipeline_locks.pop(uid, None)

    # Build a source pipeline, tag a champion weight object with a marker, pickle
    # it as the persisted model_state for "momentum".
    src = MLPipeline(uid, {})
    src.cc_models["momentum"].champion.pnl_points = 123.0     # restoration marker
    blob = pickle.dumps(src.cc_models["momentum"], protocol=pickle.HIGHEST_PROTOCOL)

    conn = PipelineConn([{"model_name": "momentum", "state": blob}])
    try:
        pipe = await get_pipeline(uid, conn)

        # No level rows → every XP tracker at the level-1 default.
        assert pipe.xp_trackers["momentum"].level == 1
        assert pipe.xp_trackers["momentum"].xp == 0
        assert all(t.level == 1 for t in pipe.xp_trackers.values())

        # …but the weights DID restore from model_state (marker survived).
        assert pipe.cc_models["momentum"].champion.pnl_points == 123.0
    finally:
        _pipelines.pop(uid, None)
        _pipeline_locks.pop(uid, None)
