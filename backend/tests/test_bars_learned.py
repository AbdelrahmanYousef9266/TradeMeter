"""
Regression test for the "bars_learned stuck / HOLD 50% deadlock" bug.

Before the fix, bars_learned only advanced when a simulated trade CLOSED, so
mostly-HOLD models (which open no trades) stayed frozen and their classifiers
never left the default 0.5 output.

After the fix, learn_all does baseline per-bar direction learning for every
model, so:
  1. bars_learned advances by exactly 1 per bar for all 8 personality models
     + personal, and
  2. the classifiers move off 0.5 (deadlock escaped).
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.services.ml.pipeline import MLPipeline
from app.services.market_data.features import FeatureEngine


class _FakeConn:
    async def execute(self, q, *a):  return None
    async def fetch(self, q, *a):    return []
    async def fetchrow(self, q, *a): return None


class _FakeRedis:
    async def publish(self, ch, msg): return None


class _Bar:
    __slots__ = ("time", "open", "high", "low", "close", "volume")

    def __init__(self, time, o, h, l, c, v):
        self.time, self.open, self.high, self.low, self.close, self.volume = time, o, h, l, c, v


def _bars(n=220):
    """A mostly-upward trending series so the classifiers get a clear signal."""
    rng = np.random.default_rng(7)
    out = []
    price = 5000.0
    t0 = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    for i in range(n):
        drift = rng.normal(0.6, 1.0)   # upward bias with noise
        open_ = price
        close = max(1.0, price + drift)
        high = max(open_, close) + abs(rng.normal(0, 0.3))
        low = min(open_, close) - abs(rng.normal(0, 0.3))
        out.append(_Bar(t0 + timedelta(minutes=i), open_, high, low, close, 1000))
        price = close
    return out


@pytest.mark.asyncio
async def test_bars_learned_advances_every_bar_and_escapes_deadlock(monkeypatch):
    # Avoid the periodic MLflow snapshot / state save during the test
    from app.core.config import settings as cfg
    monkeypatch.setattr(cfg, "model_snapshot_interval", 10**9)
    monkeypatch.setattr(cfg, "model_state_save_interval", 10**9)

    pipe = MLPipeline("00000000-0000-0000-0000-000000000001", {})
    eng = FeatureEngine()
    conn, redis = _FakeConn(), _FakeRedis()

    prev = None
    learn_calls = 0

    for bar in _bars(220):
        feats = eng.update(bar)
        if feats is None:
            continue   # warmup

        preds = await pipe.predict_all(
            feats, bar.close, current_bar_open=bar.open, bar_time=bar.time,
        )

        if prev is not None:
            await pipe.learn_all(
                features=prev["feats"],
                actual_close=bar.close,
                prev_close=prev["close"],
                predictions=prev["preds"],
                bar_high=bar.high,
                bar_low=bar.low,
                bar_time=bar.time,
                db_conn=conn,
                redis_client=redis,
            )
            learn_calls += 1

        prev = {"feats": feats, "close": bar.close, "preds": preds}

    assert learn_calls > 100, f"expected a healthy run, got {learn_calls} learn calls"

    # 1. bars_learned advanced by exactly 1 per bar for every learning model
    learning_models = [
        "scalper", "momentum", "mean_reversion", "breakout",
        "conservative", "aggressive", "volume", "contrarian", "personal",
    ]
    for name in learning_models:
        assert pipe.xp_trackers[name].bars_learned == learn_calls, (
            f"{name}.bars_learned={pipe.xp_trackers[name].bars_learned} "
            f"but there were {learn_calls} bars"
        )

    # 2. Classifiers escaped the 0.5 deadlock — at least one champion moved off 0.5
    sample = prev["feats"]
    moved = []
    for name, cc in pipe.cc_models.items():
        p_up, _ = cc._champion_model_obj._raw_proba(sample)
        moved.append(abs(p_up - 0.5) > 0.02)
    assert any(moved), "no champion classifier moved off 0.5 — still deadlocked"


@pytest.mark.asyncio
async def test_bars_learned_advances_even_with_zero_trades(monkeypatch):
    """
    The core of the bug: even if NO trades ever close, bars_learned must still
    advance. We force every trade to stay open by making the trade manager a
    no-op, then confirm bars_learned still tracks the bar count.
    """
    from app.core.config import settings as cfg
    monkeypatch.setattr(cfg, "model_snapshot_interval", 10**9)
    monkeypatch.setattr(cfg, "model_state_save_interval", 10**9)

    pipe = MLPipeline("00000000-0000-0000-0000-000000000002", {})
    # Force zero closed trades regardless of price action
    pipe.trade_manager.update_all = lambda *a, **k: []

    eng = FeatureEngine()
    conn, redis = _FakeConn(), _FakeRedis()
    prev = None
    learn_calls = 0

    for bar in _bars(160):
        feats = eng.update(bar)
        if feats is None:
            continue
        preds = await pipe.predict_all(feats, bar.close, current_bar_open=bar.open, bar_time=bar.time)
        if prev is not None:
            await pipe.learn_all(
                features=prev["feats"], actual_close=bar.close, prev_close=prev["close"],
                predictions=prev["preds"], bar_high=bar.high, bar_low=bar.low,
                bar_time=bar.time, db_conn=conn, redis_client=redis,
            )
            learn_calls += 1
        prev = {"feats": feats, "close": bar.close, "preds": preds}

    assert learn_calls > 50
    # Despite ZERO trades closing, every model still learned every bar
    assert pipe.xp_trackers["momentum"].bars_learned == learn_calls
    assert pipe.xp_trackers["personal"].bars_learned == learn_calls
