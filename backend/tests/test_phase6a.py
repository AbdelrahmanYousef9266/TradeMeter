"""
Phase 6A tests — Champion/Challenger system.
Tests cover: mutation, clamping, evaluation logic, promotion history.
"""

import pytest
from app.services.ml.champion_challenger import (
    ChampionChallenger,
    mutate_params,
    MUTATION_RATE,
    EVAL_INTERVAL,
)
from app.services.ml.models.momentum import MomentumModel


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
