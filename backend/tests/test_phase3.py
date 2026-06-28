"""
Phase 3 test suite — unit tests for XP tracking, ensemble weights, drift
detection, personality model instantiation, and the Contrarian special logic.

Run with: cd backend && pytest tests/test_phase3.py -v

Tests 1-9 are pure Python logic (no River, no I/O).
Tests 10-14 require River to be installed (it is in requirements.txt).
"""

import uuid
from collections import deque
from datetime import datetime, timezone

import pytest

from app.services.ml.xp import (
    XPTracker,
    LevelUpEvent,
    xp_for_level,
    level_to_rank,
    get_unlocked_settings,
    XP_BAR_LEARNED,
    XP_CORRECT_DIRECTION,
    XP_PNL_IMPROVEMENT,
    XP_STREAK_BONUS,
    XP_WRONG_PREDICTION,
)
from app.services.ml.ensemble import compute_blend_weights


# ── Helpers ──────────────────────────────────────────────────────────────────

def _tracker(level: int = 1, xp: int = 0, streak: int = 0) -> XPTracker:
    return XPTracker("user-1", "scalper", level=level, xp=xp, streak=streak)


def _make_features() -> dict:
    return {
        "rsi_14":        50.0,
        "ema_9":         5000.0,
        "ema_21":        4990.0,
        "ema_50":        4980.0,
        "macd":          2.5,
        "macd_signal":   1.8,
        "atr_14":        3.0,
        "volume_delta":  0.1,
        "bar_range":     4.0,
        "close_position": 0.6,
    }


# ── Test 1: Correct prediction awards full XP ─────────────────────────────────

def test_xp_award_correct_prediction():
    t = _tracker()
    # direction_up=0.7 (predicts up), actual=1 (up) → correct
    event = t.award(direction_up=0.7, actual_direction=1, prev_pnl=0.0, curr_pnl=0.001)
    expected = XP_BAR_LEARNED + XP_CORRECT_DIRECTION + XP_PNL_IMPROVEMENT
    # streak was 0 before award, so no streak bonus this bar
    assert t.xp == expected
    assert t.streak == 1


# ── Test 2: Wrong prediction deducts XP and resets streak ────────────────────

def test_xp_award_wrong_prediction():
    t = _tracker(streak=5)
    # direction_up=0.7 (predicts up), actual=0 (down) → wrong
    t.award(direction_up=0.7, actual_direction=0, prev_pnl=0.0, curr_pnl=-0.001)
    assert t.streak == 0
    # XP = XP_BAR_LEARNED + XP_WRONG_PREDICTION; no P&L improvement (curr_pnl < prev_pnl)
    expected = max(0, XP_BAR_LEARNED + XP_WRONG_PREDICTION)
    assert t.xp == expected


# ── Test 3: XP never goes below 0 ────────────────────────────────────────────

def test_xp_floor():
    t = _tracker(xp=0)
    # Force multiple wrong predictions — XP must stay at 0
    for _ in range(10):
        t.award(direction_up=0.7, actual_direction=0, prev_pnl=0.0, curr_pnl=-0.001)
    assert t.xp >= 0


# ── Test 4: Streak bonus compounds correctly ──────────────────────────────────

def test_streak_bonus():
    t = _tracker()
    # Build up a streak of 5 then award the 6th correct bar
    for _ in range(5):
        t.award(direction_up=0.7, actual_direction=1, prev_pnl=0.0, curr_pnl=0.0)

    assert t.streak == 5

    xp_before = t.xp
    # 6th correct bar: streak=5 → bonus = XP_STREAK_BONUS * 5 = 15
    t.award(direction_up=0.7, actual_direction=1, prev_pnl=0.0, curr_pnl=0.0)

    xp_gained = t.xp - xp_before
    assert xp_gained == XP_BAR_LEARNED + XP_CORRECT_DIRECTION + XP_STREAK_BONUS * 5
    assert t.streak == 6


# ── Test 5: xp_for_level at level boundaries ─────────────────────────────────

def test_xp_for_level_boundaries():
    assert xp_for_level(1)   == 300
    assert xp_for_level(19)  == 300
    assert xp_for_level(20)  == 500
    assert xp_for_level(50)  == 800
    assert xp_for_level(80)  == 1200
    assert xp_for_level(99)  == 1200
    assert xp_for_level(100) == 0     # Master — no next level


# ── Test 6: level_to_rank at tier boundaries ─────────────────────────────────

def test_level_to_rank():
    assert level_to_rank(1)   == "Rookie"
    assert level_to_rank(19)  == "Rookie"
    assert level_to_rank(20)  == "Apprentice"
    assert level_to_rank(39)  == "Apprentice"
    assert level_to_rank(40)  == "Pro"
    assert level_to_rank(60)  == "Elite"
    assert level_to_rank(80)  == "Expert"
    assert level_to_rank(100) == "Master"


# ── Test 7: get_unlocked_settings for Master returns all unlocks ──────────────

def test_master_unlocks_everything():
    unlocks = get_unlocked_settings("Master")
    assert "Base settings"          in unlocks
    assert "Confidence threshold"   in unlocks
    assert "Signal mode presets"    in unlocks
    assert "Blend weight boost"     in unlocks
    assert "Aggressive settings"    in unlocks
    assert "All settings unlocked"  in unlocks


# ── Test 8: compute_blend_weights sums to 1.0 ────────────────────────────────

def test_blend_weights_sum_to_one():
    rolling = {
        name: deque([1, 0, 1, 1, 0], maxlen=50)
        for name in [
            "scalper", "momentum", "mean_reversion", "breakout",
            "conservative", "aggressive", "volume", "contrarian",
        ]
    }
    ranks   = {name: "Rookie" for name in rolling}
    weights = compute_blend_weights(rolling, ranks, None)

    assert pytest.approx(sum(weights.values()), abs=1e-6) == 1.0


# ── Test 9: Elite model gets 1.5× blend weight boost ─────────────────────────

def test_blend_weights_elite_multiplier():
    model_names = [
        "scalper", "momentum", "mean_reversion", "breakout",
        "conservative", "aggressive", "volume", "contrarian",
    ]
    # All models same accuracy = 0.6 except contrarian which is Elite
    rolling = {name: deque([1]*30 + [0]*20, maxlen=50) for name in model_names}
    ranks   = {name: "Rookie" for name in model_names}
    ranks["contrarian"] = "Elite"

    weights = compute_blend_weights(rolling, ranks, None)

    # Contrarian should have higher weight than any Rookie model
    rookie_weight    = weights["scalper"]
    contrarian_weight = weights["contrarian"]
    assert contrarian_weight > rookie_weight
    assert pytest.approx(contrarian_weight / rookie_weight, abs=0.01) == 1.5


# ── Test 10: DriftDetector triggers after 20 consecutive wrong predictions ────

def test_drift_detector_triggers():
    from app.services.ml.drift import DriftDetector

    detector = DriftDetector("user-1", "scalper", threshold=0.60)

    # Feed 19 wrong predictions — should not trigger yet
    for i in range(19):
        result = detector.update(correct=False)
        assert result is False, f"Triggered too early at update {i+1}"

    # 20th wrong prediction — rolling_accuracy (0.0) < threshold (0.60) → triggers
    triggered = detector.update(correct=False)
    assert triggered is True


# ── Test 11: All 8 personality models instantiate without error ───────────────

def test_all_personality_models_instantiate():
    from app.services.ml.models.scalper       import ScalperModel
    from app.services.ml.models.momentum      import MomentumModel
    from app.services.ml.models.mean_reversion import MeanReversionModel
    from app.services.ml.models.breakout      import BreakoutModel
    from app.services.ml.models.conservative  import ConservativeModel
    from app.services.ml.models.aggressive    import AggressiveModel
    from app.services.ml.models.volume        import VolumeModel
    from app.services.ml.models.contrarian    import ContrarianModel

    models = [
        ScalperModel(), MomentumModel(), MeanReversionModel(), BreakoutModel(),
        ConservativeModel(), AggressiveModel(), VolumeModel(), ContrarianModel(),
    ]
    assert len(models) == 8


# ── Test 12: All 8 models return ModelPrediction with valid signal ─────────────

def test_all_models_return_valid_prediction():
    from app.services.ml.models.scalper       import ScalperModel
    from app.services.ml.models.momentum      import MomentumModel
    from app.services.ml.models.mean_reversion import MeanReversionModel
    from app.services.ml.models.breakout      import BreakoutModel
    from app.services.ml.models.conservative  import ConservativeModel
    from app.services.ml.models.aggressive    import AggressiveModel
    from app.services.ml.models.volume        import VolumeModel
    from app.services.ml.models.contrarian    import ContrarianModel
    from app.services.ml.models.base          import ModelPrediction

    features   = _make_features()
    last_close = 5000.0
    models = [
        ScalperModel(), MomentumModel(), MeanReversionModel(), BreakoutModel(),
        ConservativeModel(), AggressiveModel(), VolumeModel(), ContrarianModel(),
    ]

    for model in models:
        pred = model.predict(features, last_close)
        assert isinstance(pred, ModelPrediction), f"{model.name} did not return ModelPrediction"
        assert pred.signal in ("BUY", "SELL", "HOLD"), f"{model.name}: bad signal {pred.signal!r}"
        assert 0.0 <= pred.confidence <= 1.0, f"{model.name}: confidence out of range"
        assert 0.0 <= pred.direction_up <= 1.0


# ── Test 13: Contrarian inverts majority BUY consensus ───────────────────────

def test_contrarian_inverts_majority():
    from app.services.ml.models.contrarian import ContrarianModel
    from app.services.ml.models.base       import ModelPrediction

    model    = ContrarianModel()
    features = _make_features()

    # 5 models strongly agree on BUY
    buy_pred = ModelPrediction("BUY", 0.80, 0.80, 0.20, 5005.0, 4995.0)
    other_preds = {
        "scalper":        buy_pred,
        "momentum":       buy_pred,
        "mean_reversion": buy_pred,
        "breakout":       buy_pred,
        "conservative":   buy_pred,
        "aggressive":     ModelPrediction("HOLD", 0.50, 0.50, 0.50, 5002.0, 4998.0),
        "volume":         ModelPrediction("SELL", 0.60, 0.40, 0.60, 5001.0, 4999.0),
    }

    result = model.predict(features, 5000.0, other_predictions=other_preds)
    assert result.signal == "SELL", (
        f"Contrarian should SELL when 5 models BUY, got {result.signal!r}"
    )


# ── Test 14: PersonalModel blends from all 8 personality predictions ──────────

def test_personal_model_blends():
    from app.services.ml.models.personal import PersonalModel
    from app.services.ml.models.base     import ModelPrediction

    pm       = PersonalModel("test-user")
    features = _make_features()

    # Build 8 mock predictions all strongly BUY
    buy_pred = ModelPrediction("BUY", 0.85, 0.85, 0.15, 5010.0, 4990.0)
    preds    = {
        "scalper":        buy_pred,
        "momentum":       buy_pred,
        "mean_reversion": buy_pred,
        "breakout":       buy_pred,
        "conservative":   buy_pred,
        "aggressive":     buy_pred,
        "volume":         buy_pred,
        "contrarian":     buy_pred,
    }
    ranks = {name: "Rookie" for name in preds}

    result = pm.predict(features, preds, ranks)

    # With all 8 models strongly buying, the personal model should lean BUY
    assert result.direction_up > 0.5, (
        f"Expected direction_up > 0.5 with all-BUY consensus, got {result.direction_up}"
    )
