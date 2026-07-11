"""
Multi-timeframe Phase 2 — models run independently on 1-min AND 5-min.

Proves: feature engines are per-(user, timeframe) with no shared state; the model
set splits correctly (1-min = 9 online, no lstm; 5-min = 9 online + lstm); model
state/levels persist scoped by timeframe (same model_name, two timeframes, no
collision); and the LSTM trainer reads the 5-min series.
"""

import uuid

import pytest

from app.services.market_data import features
from app.services.market_data.features import get_engine
from app.services.ml.pipeline import (
    MLPipeline, model_names_for, ONLINE_MODEL_NAMES, ALL_MODEL_NAMES, LSTM_TIMEFRAME,
)
from app.services.ml.lstm_trainer import count_available_bars
from app.models.tick import Tick


def _tick(tf, t, price=5000.0):
    return Tick(time=t, user_id=uuid.uuid4(), symbol="MES 09-26",
                open=price, high=price + 1, low=price - 1, close=price + 0.5,
                volume=100, bar_type="hist", timeframe=tf)


# ── 1. Feature engines are per-(user, timeframe) ─────────────────────────────

def test_engines_isolated_per_timeframe():
    features._engines.clear()
    uid = str(uuid.uuid4())
    e1 = get_engine(uid, "1min")
    e5 = get_engine(uid, "5min")
    assert e1 is not e5                                   # distinct instances
    assert get_engine(uid, "1min") is e1                 # stable per (user, tf)

    from datetime import datetime, timezone
    t = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
    # Feed only the 1-min engine — the 5-min engine's state must be untouched.
    for i in range(10):
        e1.update(_tick("1min", t))
    assert e1.bar_count == 10
    assert e5.bar_count == 0
    features._engines.clear()


# ── 2. Model set splits by timeframe ─────────────────────────────────────────

def test_model_names_split_by_timeframe():
    assert model_names_for("1min") == ONLINE_MODEL_NAMES            # 9, no lstm
    assert "lstm" not in model_names_for("1min")
    assert model_names_for("5min") == ONLINE_MODEL_NAMES + ["lstm"] # 9 + lstm
    assert set(ALL_MODEL_NAMES) == set(ONLINE_MODEL_NAMES) | {"lstm"}


def test_pipeline_1min_has_no_lstm_5min_does():
    uid = str(uuid.uuid4())
    p1 = MLPipeline(uid, {}, timeframe="1min")
    p5 = MLPipeline(uid, {}, timeframe="5min")

    assert p1.lstm is None
    assert "lstm" not in p1.xp_trackers
    assert len(p1.xp_trackers) == 9

    assert p5.lstm is not None
    assert "lstm" in p5.xp_trackers
    assert len(p5.xp_trackers) == 10

    # A 1-min pipeline predicts without lstm and never raises.
    import asyncio
    feats = {k: 0.0 for k in (
        "rsi_14", "ema_9", "ema_21", "ema_50", "macd", "macd_signal", "atr_14",
        "volume_delta", "bar_range", "close_position", "vwap", "vwap_distance",
        "vwap_cross", "session_minutes", "session_phase", "is_power_hour")}
    preds = asyncio.run(p1.predict_all(feats, 5000.0))
    assert "lstm" not in preds
    assert "momentum" in preds


# ── 3. Persistence is timeframe-scoped (no collision on same model_name) ─────

class _CaptureConn:
    """Captures model_state / model_levels writes keyed by (model_name, timeframe)."""
    def __init__(self):
        self.state: dict[tuple, bytes] = {}
        self.levels: dict[tuple, int] = {}

    async def execute(self, q, *a):
        if "INTO model_state" in q:
            _uid, name, tf, _ctx, blob, _bars = a
            self.state[(name, tf)] = blob
        elif "INTO model_levels" in q:
            _uid, name, tf, _ctx, level, *_ = a
            self.levels[(name, tf)] = level

    async def fetch(self, q, *a):
        return []


@pytest.mark.asyncio
async def test_state_and_levels_persist_per_timeframe():
    uid = str(uuid.uuid4())
    conn = _CaptureConn()

    p1 = MLPipeline(uid, {}, timeframe="1min")
    p5 = MLPipeline(uid, {}, timeframe="5min")
    await p1.save_state(conn)
    await p5.save_state(conn)
    await p1._save_levels(conn)
    await p5._save_levels(conn)

    # 'momentum' persisted once per timeframe — distinct keys, no collision.
    assert ("momentum", "1min") in conn.state
    assert ("momentum", "5min") in conn.state
    assert ("momentum", "1min") in conn.levels
    assert ("momentum", "5min") in conn.levels
    # lstm level only on 5-min (1-min pipeline has no lstm tracker).
    assert ("lstm", "5min") in conn.levels
    assert ("lstm", "1min") not in conn.levels


# ── 4. LSTM trainer reads the 5-min series ───────────────────────────────────

class _TFConn:
    def __init__(self):
        self.tf_seen = None
    async def fetchrow(self, q, *a):
        self.tf_seen = a[1]         # count_available_bars passes (uuid, timeframe)
        return {"n": 0}


@pytest.mark.asyncio
async def test_lstm_counts_five_minute_bars():
    conn = _TFConn()
    await count_available_bars(conn, str(uuid.uuid4()))
    assert conn.tf_seen == LSTM_TIMEFRAME == "5min"
