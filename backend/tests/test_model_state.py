"""
Model-state persistence tests.

Verifies that pickled River weights survive a simulated restart:
  train → save_state → (new pipeline) → restore_state → predictions match.

No real database required — a FakeConn captures the BYTEA blobs in memory
and serves them back exactly like the model_state table would.
"""

import pickle

import pytest

from app.services.ml.pipeline import MLPipeline


FEATS = {
    "rsi_14": 58.0, "ema_9": 5841.0, "ema_21": 5836.0, "ema_50": 5822.0,
    "macd": 1.4, "macd_signal": 0.9, "atr_14": 3.2,
    "volume_delta": 0.2, "bar_range": 4.5, "close_position": 0.7,
    "vwap": 5839.0, "vwap_distance": 0.0006, "vwap_cross": 0.0,
    "session_minutes": 90, "session_phase": 0.23, "is_power_hour": 0.0,
}


class FakeConn:
    """Minimal stand-in for an asyncpg connection — stores model_state blobs."""

    def __init__(self):
        self.store: dict[str, bytes] = {}   # model_name -> pickled blob (single user)

    async def execute(self, query, *args):
        if "INTO model_state" in query:
            _uid, name, blob, _bars = args
            self.store[name] = blob

    async def fetch(self, query, *args):
        if "FROM model_state" in query:
            return [{"model_name": n, "state": b} for n, b in self.store.items()]
        return []


def _train(pipeline: MLPipeline, rounds: int = 30) -> None:
    """Drive learning through the Champion/Challenger wrappers + personal model."""
    for i in range(rounds):
        close = 5840.0 + i
        for name, cc in pipeline.cc_models.items():
            cc.predict(FEATS, close)
            cc.learn({
                "signal":      "BUY",
                "features":    FEATS,
                "pnl_points":  4.0,
                "won":         True,
                "exit_price":  close + 4.0,
                "exit_reason": "target",
            })
        pipeline.personal.learn_from_bar(FEATS, 1, {"momentum": True, "scalper": False})
        pipeline.bar_count += 1


# ── 1. Round-trip preserves every model's predictions ─────────────────────

@pytest.mark.asyncio
async def test_save_and_restore_preserves_predictions():
    original = MLPipeline("11111111-1111-1111-1111-111111111111", {})
    _train(original, rounds=40)

    conn = FakeConn()
    await original.save_state(conn)

    # All 8 CC models + personal were persisted
    assert set(conn.store.keys()) == set(original.cc_models.keys()) | {"personal"}

    # Simulate a restart: brand-new pipeline, then restore from saved blobs
    restored = MLPipeline("11111111-1111-1111-1111-111111111111", {})
    saved = {r["model_name"]: r["state"] for r in await conn.fetch("FROM model_state", None)}
    n = restored.restore_state(saved)
    assert n == 9   # 8 personality + personal

    # Champion predictions must match the trained pipeline exactly
    for name, cc in original.cc_models.items():
        p_orig = cc.predict(FEATS, 5900.0)
        p_rest = restored.cc_models[name].predict(FEATS, 5900.0)
        assert p_orig.signal == p_rest.signal, f"{name}: signal mismatch after restore"
        assert abs(p_orig.confidence - p_rest.confidence) < 1e-9, f"{name}: confidence drift"

    # Champion params (incl. ATR mults, eval counters) preserved
    for name, cc in original.cc_models.items():
        assert restored.cc_models[name].champion.params == cc.champion.params


# ── 2. A trained model differs from a fresh one (proves state actually loaded) ─

@pytest.mark.asyncio
async def test_restored_state_differs_from_fresh():
    original = MLPipeline("22222222-2222-2222-2222-222222222222", {})
    _train(original, rounds=60)

    conn = FakeConn()
    await original.save_state(conn)

    fresh = MLPipeline("22222222-2222-2222-2222-222222222222", {})
    # Personal classifier confidence should differ between trained-and-restored vs fresh
    fresh_pred = fresh.personal.predict(FEATS, {}, {})

    restored = MLPipeline("22222222-2222-2222-2222-222222222222", {})
    saved = {r["model_name"]: r["state"] for r in await conn.fetch("FROM model_state", None)}
    restored.restore_state(saved)
    restored_pred = restored.personal.predict(FEATS, {}, {})

    # The restored personal model carries learned weights; fresh is untrained.
    assert restored_pred.direction_up != fresh_pred.direction_up


# ── 3. Corrupt blob is skipped, not fatal ─────────────────────────────────

def test_restore_skips_corrupt_blob():
    pipeline = MLPipeline("33333333-3333-3333-3333-333333333333", {})
    fresh_momentum = pipeline.cc_models["momentum"]

    n = pipeline.restore_state({
        "momentum": b"not-a-valid-pickle-blob",
    })

    assert n == 0
    # Model left at its fresh default — pipeline still usable
    assert pipeline.cc_models["momentum"] is fresh_momentum


# ── 4. Unknown model name is skipped gracefully ───────────────────────────

def test_restore_unknown_model_name_skipped():
    pipeline = MLPipeline("44444444-4444-4444-4444-444444444444", {})
    blob = pickle.dumps(pipeline.cc_models["scalper"], protocol=pickle.HIGHEST_PROTOCOL)

    n = pipeline.restore_state({
        "scalper_v2": blob,   # not a real model name
        "scalper":    blob,   # valid
    })

    assert n == 1   # only the valid one restored
