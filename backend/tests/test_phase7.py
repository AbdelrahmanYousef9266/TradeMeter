"""
Phase 7 tests — PyTorch LSTM (Model 11).

Covers the 8 spec checks plus an end-to-end training round-trip on synthetic
OHLCV data (build_training_data → train_lstm → persist → load).
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import torch

from app.services.ml.lstm_model import (
    LSTMNet, LSTMModel,
    SEQUENCE_LENGTH, N_FEATURES, MIN_BARS_TO_ACTIVATE, FEATURE_ORDER,
)
from app.services.ml.lstm_trainer import (
    label_from_move, build_training_data, train_lstm, count_available_bars,
)
from app.services.market_data.features import FeatureEngine


def _features(val=0.5):
    return {k: val for k in FEATURE_ORDER}


# ── 1. LSTMNet forward pass: (1, 50, 16) → (1, 3) ────────────────────────────

def test_lstmnet_forward_shape():
    net = LSTMNet()
    net.eval()
    x = torch.randn(1, SEQUENCE_LENGTH, N_FEATURES)
    out = net(x)
    assert out.shape == (1, 3)


# ── 2. predict() returns HOLD when not trained ───────────────────────────────

def test_predict_hold_when_untrained():
    m = LSTMModel("u1")
    # Fill the window so only the "untrained" condition blocks prediction
    for _ in range(SEQUENCE_LENGTH):
        m.add_features(_features())
    pred = m.predict(_features(), last_close=5840.0)
    assert pred.signal == "HOLD"
    assert pred.confidence == 0.0


# ── 3. predict() returns HOLD when window not full (even if trained) ──────────

def test_predict_hold_when_window_not_full():
    m = LSTMModel("u1")
    m.is_trained = True   # pretend trained
    # Only one bar in the window after this predict() → can't predict yet
    pred = m.predict(_features(), last_close=5840.0)
    assert pred.signal == "HOLD"
    assert len(m.feature_window) < SEQUENCE_LENGTH


# ── 4. can_predict() False when untrained (even with a full window) ──────────

def test_can_predict_false_when_untrained():
    m = LSTMModel("u1")
    for _ in range(SEQUENCE_LENGTH):
        m.add_features(_features())
    assert len(m.feature_window) == SEQUENCE_LENGTH
    assert m.is_trained is False
    assert m.can_predict() is False


# ── 5. serialize/load round trip preserves is_trained + stats ────────────────

def test_serialize_load_roundtrip():
    m = LSTMModel("u1")
    m.is_trained = True
    m.feature_means = np.arange(N_FEATURES, dtype=np.float32)
    m.feature_stds = np.full(N_FEATURES, 2.0, dtype=np.float32)
    m.train_accuracy = 0.61
    m.train_samples = 1234

    blob = m.serialize()

    restored = LSTMModel("u1")
    assert restored.is_trained is False  # fresh
    restored.load(blob)

    assert restored.is_trained is True
    assert restored.train_accuracy == 0.61
    assert restored.train_samples == 1234
    assert np.allclose(restored.feature_means, m.feature_means)
    assert np.allclose(restored.feature_stds, m.feature_stds)


# ── 6. build_training_data returns None when < MIN_BARS_TO_ACTIVATE ──────────

@pytest.mark.asyncio
async def test_build_training_data_insufficient():
    class _Conn:
        async def fetch(self, q, *a):
            # Far fewer than MIN_BARS_TO_ACTIVATE rows
            return [{"time": datetime.now(timezone.utc), "open": 1.0, "high": 1.0,
                     "low": 1.0, "close": 1.0, "volume": 1, "bar_type": "1min"}
                    for _ in range(100)]

    result = await build_training_data(_Conn(), str(uuid.uuid4()))
    assert result is None


# ── 7. label logic — move vs 0.5*ATR thresholds ──────────────────────────────

def test_label_from_move():
    atr = 4.0  # 0.5*atr = 2.0
    assert label_from_move(3.0, atr) == 2    # BUY  (> 2.0)
    assert label_from_move(-3.0, atr) == 0   # SELL (< -2.0)
    assert label_from_move(1.0, atr) == 1    # HOLD (within band)
    assert label_from_move(2.0, atr) == 1    # exactly 0.5*atr → not strictly greater → HOLD
    assert label_from_move(-2.0, atr) == 1   # exactly -0.5*atr → HOLD


# ── 8. feature ordering matches FEATURE_ORDER (16 features) ───────────────────

def test_feature_order_matches_engine():
    assert len(FEATURE_ORDER) == 16 == N_FEATURES
    assert len(set(FEATURE_ORDER)) == 16   # no duplicates

    # The names must exactly match what the live FeatureEngine emits
    eng = FeatureEngine()
    feats = None
    t = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)

    class _Bar:
        def __init__(self, i):
            self.time = t + timedelta(minutes=i)
            self.open = 5840.0 + i * 0.1
            self.high = self.open + 1
            self.low = self.open - 1
            self.close = self.open + 0.5
            self.volume = 1000

    i = 0
    while feats is None and i < 60:
        feats = eng.update(_Bar(i))
        i += 1
    assert feats is not None
    # Metadata keys (leading '_', e.g. _close) ride alongside the 16 ML features
    # but are excluded from training — the ML feature set must match FEATURE_ORDER.
    ml_keys = {k for k in feats.keys() if not k.startswith("_")}
    assert set(FEATURE_ORDER) == ml_keys


# ── 9. End-to-end: synthetic history → train → persist → reload ──────────────

def _synthetic_rows(n=2200):
    """A gently trending random walk with 1-minute bars."""
    rng = np.random.default_rng(42)
    rows = []
    price = 5840.0
    t0 = datetime(2026, 5, 1, 13, 30, tzinfo=timezone.utc)
    for i in range(n):
        drift = rng.normal(0, 1.5)
        open_ = price
        close = max(1.0, price + drift)
        high = max(open_, close) + abs(rng.normal(0, 0.5))
        low = min(open_, close) - abs(rng.normal(0, 0.5))
        rows.append({
            "time": t0 + timedelta(minutes=i),
            "open": open_, "high": high, "low": low, "close": close,
            "volume": int(800 + abs(rng.normal(0, 200))),
            "bar_type": "1min",
        })
        price = close
    return rows


class _E2EConn:
    """Fake asyncpg conn: serves synthetic rows, captures the persisted blob."""

    def __init__(self, rows):
        self.rows = rows
        self.saved = {}   # (model_name) -> state blob

    async def fetch(self, q, *a):
        return self.rows

    async def fetchrow(self, q, *a):
        # count_available_bars now counts DISTINCT timestamps (dedup fix); the
        # synthetic rows all have distinct times, so the count is len(rows).
        if "COUNT(" in q:
            return {"n": len(self.rows)}
        return None

    async def execute(self, q, *a):
        if "INTO model_state" in q:
            # args: (user_id, state_blob, bars_count)
            self.saved["lstm"] = a[1]


@pytest.mark.asyncio
async def test_train_lstm_end_to_end():
    rows = _synthetic_rows(2200)
    conn = _E2EConn(rows)
    user_id = str(uuid.uuid4())

    assert await count_available_bars(conn, user_id) == 2200

    # Keep epochs low so the test is fast; still exercises the full path
    result = await train_lstm(conn, user_id, epochs=2)

    assert result["success"] is True
    assert result["train_samples"] > 0
    assert 0.0 <= result["val_accuracy"] <= 1.0
    assert set(result["class_distribution"].keys()) == {"SELL", "HOLD", "BUY"}

    # A blob was persisted and reloads into a trained model
    assert "lstm" in conn.saved
    restored = LSTMModel(user_id)
    restored.load(conn.saved["lstm"])
    assert restored.is_trained is True
    assert restored.train_samples == result["train_samples"]

    # Reloaded model can run live inference once its window is full
    for _ in range(SEQUENCE_LENGTH):
        restored.add_features(_features(0.5))
    pred = restored.predict(_features(0.5), last_close=5850.0)
    assert pred.signal in ("BUY", "SELL", "HOLD")
    assert 0.0 <= pred.confidence <= 1.0


# ── 10. Training does NOT block the event loop (runs in asyncio.to_thread) ────

@pytest.mark.asyncio
async def test_training_does_not_block_event_loop():
    rows = _synthetic_rows(2200)
    conn = _E2EConn(rows)
    user_id = str(uuid.uuid4())

    ticks = 0
    done = False

    async def heartbeat():
        nonlocal ticks
        while not done:
            await asyncio.sleep(0.005)
            ticks += 1

    async def run_train():
        nonlocal done
        try:
            return await train_lstm(conn, user_id, epochs=5)
        finally:
            done = True

    hb = asyncio.create_task(heartbeat())
    result = await run_train()
    await hb

    assert result["success"] is True
    # If the blocking torch work ran on the loop, the heartbeat could not tick.
    # With asyncio.to_thread it keeps ticking throughout training.
    assert ticks >= 3, f"event loop appears blocked during training (ticks={ticks})"
