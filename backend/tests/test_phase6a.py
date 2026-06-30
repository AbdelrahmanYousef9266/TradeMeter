"""
Phase 6A tests — Champion/Challenger system.
Tests cover: mutation, clamping, evaluation logic, promotion history,
Contrarian kwargs forwarding.
"""

import pytest
from app.services.ml.champion_challenger import (
    ChampionChallenger,
    mutate_params,
    MUTATION_RATE,
    EVAL_INTERVAL,
)
from app.services.ml.models.momentum import MomentumModel
from app.services.ml.models.contrarian import ContrarianModel


BASE_PARAMS = {
    "min_confidence":          0.62,
    "max_signals_per_session": 20,
    "signal_mode":             "balanced",
    "learning_rate":           0.05,
    "atr_stop_mult":           1.5,
    "atr_target_mult":         3.0,
}


# ── 1. mutate_params — values within MUTATION_RATE bounds ─────────────────

def test_mutate_params_within_bounds():
    for _ in range(200):
        mutated = mutate_params(BASE_PARAMS)
        for key, orig in BASE_PARAMS.items():
            if isinstance(orig, float):
                lo = orig * (1 - MUTATION_RATE - 0.01)
                hi = orig * (1 + MUTATION_RATE + 0.01)
                assert lo <= mutated[key] <= hi, f"{key}: {mutated[key]} outside [{lo}, {hi}]"


# ── 2. mutate_params — min_confidence never below 0.50 ───────────────────

def test_mutate_params_min_confidence_floor():
    very_low = dict(BASE_PARAMS, min_confidence=0.50)
    for _ in range(100):
        mutated = mutate_params(very_low)
        assert mutated["min_confidence"] >= 0.50


# ── 3. mutate_params — atr_stop_mult never below 0.5 ─────────────────────

def test_mutate_params_atr_stop_floor():
    very_low = dict(BASE_PARAMS, atr_stop_mult=0.5)
    for _ in range(100):
        mutated = mutate_params(very_low)
        assert mutated["atr_stop_mult"] >= 0.5


# ── 4. ChampionChallenger — challenger promoted when higher P&L ───────────

def test_challenger_promoted():
    cc = ChampionChallenger("momentum", MomentumModel, BASE_PARAMS)
    old_champion_params = dict(cc.champion.params)

    # Give challenger higher P&L
    cc.challenger.pnl_points = 10.0
    cc.champion.pnl_points   = 5.0
    cc.bars_since_eval       = EVAL_INTERVAL

    event = cc.maybe_evaluate()

    assert event is not None
    assert event.winner         == "challenger"
    assert event.challenger_pnl == 10.0
    assert event.champion_pnl   == 5.0
    # New champion should have the old challenger's params
    assert cc.champion.params   == event.new_params


# ── 5. ChampionChallenger — champion retained when higher P&L ────────────

def test_champion_retained():
    cc = ChampionChallenger("momentum", MomentumModel, BASE_PARAMS)
    original_champion_params = dict(cc.champion.params)

    cc.champion.pnl_points   = 8.0
    cc.challenger.pnl_points = 3.0
    cc.bars_since_eval       = EVAL_INTERVAL

    event = cc.maybe_evaluate()

    assert event is None
    # Champion params should be unchanged
    assert cc.champion.params == original_champion_params


# ── 6. ChampionChallenger — new challenger spawned after evaluation ───────

def test_new_challenger_spawned():
    cc = ChampionChallenger("momentum", MomentumModel, BASE_PARAMS)
    old_challenger_model = cc._challenger_model_obj

    cc.bars_since_eval = EVAL_INTERVAL
    cc.maybe_evaluate()

    assert cc._challenger_model_obj is not old_challenger_model


# ── 7. ChampionChallenger — new challenger params differ from champion ────

def test_new_challenger_params_different():
    cc = ChampionChallenger("momentum", MomentumModel, BASE_PARAMS)
    original = dict(cc.champion.params)

    cc.bars_since_eval = EVAL_INTERVAL
    cc.maybe_evaluate()

    # At least one float param should differ (mutation applied)
    float_keys = [k for k, v in original.items() if isinstance(v, float)]
    diffs = [cc.challenger.params[k] != original[k] for k in float_keys]
    assert any(diffs), "Challenger params should be mutated from champion"


# ── 8. ChampionChallenger — promotion_history records correctly ───────────

def test_promotion_history():
    cc = ChampionChallenger("momentum", MomentumModel, BASE_PARAMS)

    # Force challenger wins three times
    for i in range(3):
        cc.challenger.pnl_points = 10.0 + i
        cc.champion.pnl_points   = 5.0
        cc.bars_since_eval       = EVAL_INTERVAL
        cc.maybe_evaluate()

    assert len(cc.promotion_history) == 3
    for entry in cc.promotion_history:
        assert entry.winner          == "challenger"
        assert entry.bars_evaluated  == EVAL_INTERVAL


# ── 9. get_status — returns status for all 8 models ──────────────────────

def test_get_status_structure():
    cc = ChampionChallenger("momentum", MomentumModel, BASE_PARAMS)
    status = cc.get_status()

    assert "champion"          in status
    assert "challenger"        in status
    assert "bars_since_eval"   in status
    assert "bars_until_eval"   in status
    assert "eval_interval"     in status
    assert "promotion_history" in status

    assert status["champion"]["version_id"]   == "champion"
    assert status["challenger"]["version_id"] == "challenger"
    assert status["eval_interval"]            == EVAL_INTERVAL


# ── 10. maybe_evaluate — no-op before EVAL_INTERVAL bars ─────────────────

def test_no_evaluation_before_interval():
    cc = ChampionChallenger("momentum", MomentumModel, BASE_PARAMS)
    cc.challenger.pnl_points = 999.0
    cc.bars_since_eval       = EVAL_INTERVAL - 1

    event = cc.maybe_evaluate()

    assert event is None
    assert cc.bars_since_eval == EVAL_INTERVAL - 1  # not reset


# ── 11. Contrarian kwargs forwarding through CC wrapper ───────────────────

from app.services.ml.models.base import ModelPrediction

CONTRARIAN_PARAMS = {
    "min_confidence":          0.58,
    "max_signals_per_session": 15,
    "signal_mode":             "balanced",
    "atr_stop_mult":           1.0,
    "atr_target_mult":         2.5,
}

DUMMY_FEATURES = {
    "rsi_14": 55.0, "ema_9": 5840.0, "ema_21": 5835.0, "ema_50": 5820.0,
    "macd": 1.2, "macd_signal": 0.8, "atr_14": 3.5,
    "volume_delta": 0.1, "bar_range": 4.0, "close_position": 0.6,
    "vwap": 5838.0, "vwap_distance": 0.0004, "vwap_cross": 0.0,
    "session_minutes": 120, "session_phase": 0.31, "is_power_hour": 0.0,
}

def _make_pred(signal, p_up):
    return ModelPrediction(
        signal=signal, confidence=max(p_up, 1 - p_up),
        direction_up=p_up, direction_down=1 - p_up,
        predicted_high=5844.0, predicted_low=5836.0,
    )

# 5 of 7 are BUY → Contrarian should SELL (consensus threshold=5)
DUMMY_PREDICTIONS = {
    "scalper":        _make_pred("BUY",  0.70),
    "momentum":       _make_pred("BUY",  0.65),
    "mean_reversion": _make_pred("SELL", 0.35),
    "breakout":       _make_pred("BUY",  0.60),
    "conservative":   _make_pred("HOLD", 0.50),
    "aggressive":     _make_pred("BUY",  0.68),
    "volume":         _make_pred("BUY",  0.62),
}


def test_contrarian_receives_other_predictions_through_cc():
    """
    ChampionChallenger.predict() forwards **kwargs so Contrarian's
    `other_predictions` argument passes through to both model instances.
    5 of 7 models are BUY → Contrarian should output SELL.
    """
    cc = ChampionChallenger("contrarian", ContrarianModel, CONTRARIAN_PARAMS)

    # Should not raise — Contrarian reads other_predictions inside predict()
    result = cc.predict(DUMMY_FEATURES, 5840.0, other_predictions=DUMMY_PREDICTIONS)

    assert isinstance(result, ModelPrediction)
    assert result.signal in ("BUY", "SELL", "HOLD")
    assert 0.0 <= result.confidence <= 1.0
    # 5 BUYs ≥ consensus_threshold(5) → Contrarian should SELL (unless gated by confidence)
    # Result is SELL or HOLD (if confidence < min_confidence at startup); never BUY
    assert result.signal != "BUY", (
        f"Contrarian saw 5/7 BUY consensus but returned {result.signal} — "
        "kwargs not reaching the model through CC wrapper"
    )


def test_contrarian_cc_without_kwargs_does_not_crash():
    """
    Calling CC.predict() WITHOUT other_predictions should also work
    (Contrarian falls back to own classifier which returns HOLD pre-training).
    """
    cc = ChampionChallenger("contrarian", ContrarianModel, CONTRARIAN_PARAMS)
    result = cc.predict(DUMMY_FEATURES, 5840.0)

    assert isinstance(result, ModelPrediction)
