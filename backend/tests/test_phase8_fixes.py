"""
Regression tests for the Phase-8 correctness fixes.

  BUG 1 — simulated trades fill at the genuinely NEXT bar's open (no look-ahead).
  BUG 2 — a bar whose range spans both stop and target resolves as a LOSS.
  BUG 4 — a Challenger CAN be promoted when its own trades outperform.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.ml.pipeline import MLPipeline
from app.services.ml.trade_tracker import SimulatedTrade
from app.services.ml.champion_challenger import ChampionChallenger, EVAL_INTERVAL
from app.services.ml.models.momentum import MomentumModel
from app.services.ml.models.base import ModelPrediction


FEATS = {
    "rsi_14": 58.0, "ema_9": 5841.0, "ema_21": 5836.0, "ema_50": 5822.0,
    "macd": 1.4, "macd_signal": 0.9, "atr_14": 4.0,
    "volume_delta": 0.2, "bar_range": 4.5, "close_position": 0.7,
    "vwap": 5839.0, "vwap_distance": 0.0006, "vwap_cross": 0.0,
    "session_minutes": 90, "session_phase": 0.23, "is_power_hour": 0.0,
    "_close": 5845.0,
}

# 14:30 UTC in June → 10:30 ET — safely inside the RTH session (no timeout).
_T0 = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)

BASE_PARAMS = {
    "min_confidence":  0.62, "max_signals_per_session": 20,
    "signal_mode":     "balanced", "learning_rate": 0.05,
    "atr_stop_mult":   1.5, "atr_target_mult": 3.0,
}


# ── BUG 1 — trade fills at the NEXT bar's open, not the signal bar's ─────────

@pytest.mark.asyncio
async def test_trade_fills_at_next_bar_open(monkeypatch):
    from app.core.config import settings as cfg
    monkeypatch.setattr(cfg, "model_snapshot_interval", 10**9)
    monkeypatch.setattr(cfg, "model_state_save_interval", 10**9)

    pipe = MLPipeline("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", {})

    # Force momentum's champion to always fire BUY so a trade is generated.
    buy = ModelPrediction("BUY", 0.9, 0.9, 0.1, 5900.0, 5800.0)
    monkeypatch.setattr(
        pipe.cc_models["momentum"]._champion_model_obj,
        "predict", lambda *a, **k: buy,
    )

    bar1_open, bar1_close = 5840.0, 5845.0
    bar2_open, bar2_close = 5860.0, 5865.0
    t1, t2 = _T0, _T0 + timedelta(minutes=1)

    # Bar 1: signal generated and BUFFERED — no trade opened on the signal bar.
    await pipe.predict_all(FEATS, bar1_close, current_bar_open=bar1_open, bar_time=t1)
    assert not pipe.trade_manager.open_trades.get("momentum"), \
        "trade must NOT open on the same bar the signal was derived from"
    assert any(s["model_name"] == "momentum" for s in pipe._pending_champion)

    # Bar 2: the buffered signal fills at THIS bar's open (the genuine next bar).
    await pipe.predict_all(FEATS, bar2_close, current_bar_open=bar2_open, bar_time=t2)
    trades = pipe.trade_manager.open_trades["momentum"]
    assert len(trades) == 1
    assert trades[0].entry_price == bar2_open, \
        f"entry {trades[0].entry_price} should be next bar open {bar2_open}, not {bar1_open}"


# ── BUG 2 — both-touched bar resolves pessimistically as a stop (loss) ───────

def test_intrabar_both_touched_buy_resolves_as_loss():
    trade = SimulatedTrade(
        model_name="m", user_id="u", signal="BUY",
        entry_price=100.0, stop_loss=98.0, take_profit=104.0,
        entry_time=_T0, confidence=0.6, features={},
    )
    # Bar spans 97..105 → touches BOTH the 98 stop and the 104 target.
    closed = trade.update(bar_high=105.0, bar_low=97.0, bar_close=100.0, bar_time=_T0)
    assert closed is True
    assert trade.exit_reason == "stop"
    assert trade.won is False
    assert trade.exit_price == 98.0


def test_intrabar_both_touched_sell_resolves_as_loss():
    trade = SimulatedTrade(
        model_name="m", user_id="u", signal="SELL",
        entry_price=100.0, stop_loss=102.0, take_profit=96.0,
        entry_time=_T0, confidence=0.6, features={},
    )
    # Bar spans 95..103 → touches BOTH the 102 stop and the 96 target.
    closed = trade.update(bar_high=103.0, bar_low=95.0, bar_close=100.0, bar_time=_T0)
    assert closed is True
    assert trade.exit_reason == "stop"
    assert trade.won is False
    assert trade.exit_price == 102.0


# ── BUG 4 — challenger can be promoted from its OWN, independent P&L ─────────

def test_challenger_can_be_promoted_from_independent_trades():
    cc = ChampionChallenger("momentum", MomentumModel, BASE_PARAMS)

    losing = {"signal": "BUY", "features": FEATS, "pnl_points": -3.0,
              "won": False, "exit_price": 0.0, "exit_reason": "stop"}
    winning = {"signal": "BUY", "features": FEATS, "pnl_points": 5.0,
               "won": True, "exit_price": 0.0, "exit_reason": "target"}

    # Champion's own trades lose; challenger's own trades win — the two P&Ls
    # accumulate independently (the core of the fix).
    for _ in range(5):
        cc.learn_champion(losing)
        cc.learn_challenger(winning)

    assert cc.champion.pnl_points == pytest.approx(-15.0)
    assert cc.challenger.pnl_points == pytest.approx(25.0)

    cc.bars_since_eval = EVAL_INTERVAL
    event = cc.maybe_evaluate()

    assert event is not None, "challenger outperformed but was not promoted"
    assert event.winner == "challenger"
    assert event.challenger_pnl == pytest.approx(25.0)
    assert event.champion_pnl == pytest.approx(-15.0)
