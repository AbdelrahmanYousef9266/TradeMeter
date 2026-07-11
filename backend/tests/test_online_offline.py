"""
ONLINE/OFFLINE context separation.

Guarantees:
  • live and offline feature engines are separate instances (no shared state),
  • offline learning NEVER mutates the live models,
  • an offline pipeline is seeded as a deep COPY of the current live weights,
  • promotion copies offline weights into live and a reloaded live pipeline then
    predicts like the offline model did,
  • warm-start primes a fresh engine past the 50-bar warmup (features only).
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.tick import Tick
from app.services.market_data import features as feat_mod
from app.services.market_data.features import (
    FeatureEngine, get_engine, warm_start_engine, _WARMUP_BARS,
)
from app.services.ml.models.base import ml_features
from app.services.ml.pipeline import MLPipeline, get_pipeline, _pipelines, _pipeline_locks


UID = "abcdef01-2345-6789-abcd-ef0123456789"

FEATS = {
    "rsi_14": 61.0, "ema_9": 5841.0, "ema_21": 5836.0, "ema_50": 5822.0,
    "macd": 1.4, "macd_signal": 0.9, "atr_14": 4.0, "volume_delta": 0.3,
    "bar_range": 4.5, "close_position": 0.8, "vwap": 5839.0,
    "vwap_distance": 0.0007, "vwap_cross": 0.0, "session_minutes": 95,
    "session_phase": 0.24, "is_power_hour": 0.0, "_close": 5845.0,
}


@pytest.fixture(autouse=True)
def _clean():
    feat_mod._engines.clear()
    for k in [k for k in _pipelines if k[0] == UID]:
        _pipelines.pop(k, None)
    for k in [k for k in _pipeline_locks if k[0] == UID]:
        _pipeline_locks.pop(k, None)
    yield
    feat_mod._engines.clear()
    for k in [k for k in _pipelines if k[0] == UID]:
        _pipelines.pop(k, None)
    for k in [k for k in _pipeline_locks if k[0] == UID]:
        _pipeline_locks.pop(k, None)


def _mk_tick(i):
    p = 5000.0 + (i % 20) * 0.25
    return Tick(time=datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc),
                user_id=uuid.UUID(UID), symbol="MES", open=p, high=p + 1,
                low=p - 1, close=p + 0.5, volume=100, bar_type="1min", timeframe="1min")


# ── In-memory model_state store standing in for the DB ─────────────────────────

class StateConn:
    """Stores model_state blobs keyed by (model_name, timeframe, context)."""
    def __init__(self):
        self.state: dict[tuple, bytes] = {}

    async def fetch(self, q, *a):
        if "FROM model_state" in q:
            _uid, tf, ctx = a
            return [{"model_name": n, "state": b}
                    for (n, t, c), b in self.state.items() if t == tf and c == ctx]
        return []   # model_levels → defaults

    async def execute(self, q, *a):
        if "INTO model_state" in q:
            _uid, name, tf, ctx, blob, _bars = a
            self.state[(name, tf, ctx)] = blob
        # model_levels / predictions writes are ignored for this test

    async def fetchrow(self, q, *a):
        return None

    async def fetchval(self, q, *a):
        return None


def _proba(pipeline, name=" momentum".strip()):
    return pipeline.cc_models[name]._champion_model_obj._raw_proba(FEATS)


def _train_direction(pipeline, name, direction, rounds=40):
    obj = pipeline.cc_models[name]._champion_model_obj
    for _ in range(rounds):
        obj.classifier.learn_one(ml_features(FEATS), direction)


# ── 1. Engines are per-context ─────────────────────────────────────────────────

def test_engines_isolated_per_context():
    live = get_engine(UID, "5min", "live")
    offline = get_engine(UID, "5min", "offline")
    assert live is not offline
    assert get_engine(UID, "5min", "live") is live   # stable

    for _ in range(10):
        live.update(_mk_tick(0))
    assert live.bar_count == 10
    assert offline.bar_count == 0   # untouched


# ── 2. Offline learning never mutates live ─────────────────────────────────────

def test_offline_learning_does_not_mutate_live():
    live = MLPipeline(UID, {}, timeframe="1min", context="live")
    offline = MLPipeline(UID, {}, timeframe="1min", context="offline")

    before = _proba(live, "momentum")
    _train_direction(offline, "momentum", 1, rounds=60)

    assert _proba(live, "momentum") == before          # live unchanged
    assert _proba(offline, "momentum") != before        # offline diverged


# ── 3. Offline pipeline is seeded as a deep copy of live ───────────────────────

@pytest.mark.asyncio
async def test_offline_seeds_as_copy_of_live():
    conn = StateConn()
    live = await get_pipeline(UID, conn, "1min", "live")
    _train_direction(live, "momentum", 1, rounds=50)
    await live.save_state(conn)

    offline = await get_pipeline(UID, conn, "1min", "offline")

    # Seeded from live → identical prediction at creation.
    assert _proba(offline, "momentum") == _proba(live, "momentum")


# ── 4. Promotion copies offline weights into live ──────────────────────────────

@pytest.mark.asyncio
async def test_promotion_makes_live_predict_like_offline():
    conn = StateConn()
    live = await get_pipeline(UID, conn, "1min", "live")
    _train_direction(live, "momentum", 1, rounds=50)   # live leans UP
    await live.save_state(conn)

    offline = await get_pipeline(UID, conn, "1min", "offline")
    _train_direction(offline, "momentum", 0, rounds=120)  # offline leans DOWN
    await offline.save_state(conn)

    live_before = _proba(live, "momentum")
    offline_p   = _proba(offline, "momentum")
    assert live_before != offline_p   # genuinely diverged

    # Simulate POST /models/promote: copy offline online-model blobs → live rows.
    for (name, tf, ctx), blob in list(conn.state.items()):
        if ctx == "offline" and name != "lstm":
            conn.state[(name, tf, "live")] = blob
    # Evict + reload the live pipeline (what the endpoint does).
    _pipelines.pop((UID, "1min", "live"), None)
    _pipeline_locks.pop((UID, "1min", "live"), None)

    new_live = await get_pipeline(UID, conn, "1min", "live")
    assert _proba(new_live, "momentum") == offline_p   # live now matches promoted offline


# ── 5. Warm-start exits warmup immediately (features only) ─────────────────────

def test_warm_start_exits_warmup():
    engine = FeatureEngine()
    bars = [_mk_tick(i) for i in range(_WARMUP_BARS + 5)]   # ≥ 50 stored bars

    fed = warm_start_engine(engine, bars)

    assert fed == _WARMUP_BARS + 5
    assert engine.bar_count >= _WARMUP_BARS
    # The next real bar produces features instead of None (warmup already cleared).
    assert engine.update(_mk_tick(99)) is not None
