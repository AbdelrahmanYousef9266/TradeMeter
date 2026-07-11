"""
Regression tests for the "all models HOLD forever" bug.

Root cause: each personality model gates signals with a per-session budget
(`max_signals_per_session`). The counter `_session_signal_count`

  1. was pickled into model_state, so a model that spent its budget during a
     training reprocess came back from a restart already AT the cap, and
  2. was only ever cleared by reset_session(), which nothing called.

Together these force-HOLD'd every live bar (confidence 1.0 yet signal HOLD)
after a restart or a long run. The fix: never persist the counter (pickle hooks
reset it to 0) and reset it at each RTH session (ET day) boundary in the
pipeline before predicting.
"""

import pickle
from datetime import datetime, timezone

import pytest

from app.services.ml.models.momentum import MomentumModel
from app.services.ml.pipeline import MLPipeline


UID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_session_counter_not_persisted_across_pickle():
    """A model at its per-session cap must come back from pickle with a fresh
    budget — otherwise a restored model HOLDs from bar 1."""
    m = MomentumModel()
    m._session_signal_count = 999          # simulate "budget exhausted"

    restored = pickle.loads(pickle.dumps(m))

    assert restored._session_signal_count == 0


def test_pipeline_resets_session_budget_on_new_day():
    """predict_all must clear every model's per-session signal budget when the
    ET calendar day rolls over, so capped models start firing again."""
    pipe = MLPipeline(UID, {}, timeframe="1min")

    # Exhaust the budget on every champion + challenger model.
    for cc in pipe.cc_models.values():
        cc._champion_model_obj._session_signal_count = 10_000
        cc._challenger_model_obj._session_signal_count = 10_000

    day1 = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)  # 10:30 ET
    day2 = datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc)  # next session

    # First bar of a session only records the date — it must NOT reset (the
    # budget legitimately carries within a single session).
    pipe._maybe_reset_session(day1)
    assert all(
        cc._champion_model_obj._session_signal_count == 10_000
        for cc in pipe.cc_models.values()
    )

    # Crossing into the next ET day clears the budget for champion AND challenger.
    pipe._maybe_reset_session(day2)
    assert all(
        cc._champion_model_obj._session_signal_count == 0
        and cc._challenger_model_obj._session_signal_count == 0
        for cc in pipe.cc_models.values()
    )


@pytest.mark.asyncio
async def test_capped_model_holds_then_fires_after_session_reset():
    """End-to-end: a model at its cap emits HOLD, and after a session rollover
    the same high-confidence setup produces a real BUY/SELL again."""
    pipe = MLPipeline(UID, {}, timeframe="1min")
    mom = pipe.cc_models["momentum"]._champion_model_obj

    feats = {
        "rsi_14": 58.0, "ema_9": 5841.0, "ema_21": 5836.0, "ema_50": 5822.0,
        "macd": 1.4, "macd_signal": 0.9, "atr_14": 4.0, "volume_delta": 0.2,
        "bar_range": 4.5, "close_position": 0.7, "vwap": 5839.0,
        "vwap_distance": 0.0006, "vwap_cross": 0.0, "session_minutes": 90,
        "session_phase": 0.23, "is_power_hour": 0.0, "_close": 5845.0,
    }

    # Force a confident directional call regardless of training state.
    mom._raw_proba = lambda *a, **k: (0.95, 0.05)

    # At cap → gated to HOLD even at 0.95 confidence.
    mom._session_signal_count = mom.settings["max_signals_per_session"]
    assert mom.predict(feats, 5845.0).signal == "HOLD"

    # Establish the session date, then roll to the next ET day via the pipeline.
    pipe._maybe_reset_session(datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc))
    pipe._maybe_reset_session(datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc))

    assert mom._session_signal_count == 0
    assert mom.predict(feats, 5845.0).signal == "BUY"
