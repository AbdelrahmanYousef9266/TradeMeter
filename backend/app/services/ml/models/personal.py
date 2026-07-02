"""
Personal hybrid model — one instance per user (scoped by user_id).

Blends predictions from the 8 personality models weighted by their rolling
50-bar accuracy, with optional rank multipliers and user manual overrides.
Also maintains its own LogisticRegression classifier that learns from
user-manually-marked trade outcomes, contributing user_weight fraction
to the final signal.
"""

from collections import deque

from river import linear_model, optim

from app.services.ml.models.base import ModelPrediction, ml_features
from app.services.ml.ensemble import compute_blend_weights


_PERSONALITY_NAMES = [
    "scalper", "momentum", "mean_reversion", "breakout",
    "conservative", "aggressive", "volume", "contrarian",
]


class PersonalModel:
    """Used for both Model 9 (you) and Model 10 (brother)."""

    name = "personal"

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

        # Rolling 50-bar accuracy per personality model
        self.rolling_accuracy: dict[str, deque] = {
            name: deque(maxlen=50) for name in _PERSONALITY_NAMES
        }

        # User-set manual blend weights (None = auto from accuracy)
        self.manual_weights: dict[str, float] | None = None

        # Own classifier — learns from user decision outcomes
        self.user_classifier = linear_model.LogisticRegression(optimizer=optim.SGD(0.05))

        self.settings = self._default_settings()
        self.bar_count = 0

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.60,
            "max_signals_per_session": 20,
            "user_weight": 0.25,
            "auto_blend": True,
        }

    # ── Prediction ────────────────────────────────────────────────────────

    def predict(
        self,
        features:         dict,
        model_predictions: dict[str, ModelPrediction],
        level_ranks:      dict[str, str],
    ) -> ModelPrediction:
        weights = compute_blend_weights(
            self.rolling_accuracy, level_ranks, self.manual_weights
        )

        # Weighted sum of direction_up from personality models
        blend_up = sum(
            model_predictions[name].direction_up * w
            for name, w in weights.items()
            if name in model_predictions
        )

        # Own classifier's probability
        try:
            own_proba = self.user_classifier.predict_proba_one(ml_features(features))
            own_up    = own_proba.get(1, 0.5) if own_proba else 0.5
        except Exception:
            own_up = 0.5

        user_w  = self.settings.get("user_weight", 0.25)
        final_up   = blend_up * (1.0 - user_w) + own_up * user_w
        final_down = 1.0 - final_up
        confidence = max(final_up, final_down)

        min_conf = self.settings.get("min_confidence", 0.60)
        if confidence < min_conf:
            signal = "HOLD"
        elif final_up > final_down:
            signal = "BUY"
        else:
            signal = "SELL"

        # Target = simple average across contributing models
        highs = [model_predictions[n].predicted_high for n in weights if n in model_predictions]
        lows  = [model_predictions[n].predicted_low  for n in weights if n in model_predictions]
        ph = sum(highs) / len(highs) if highs else 0.0
        pl = sum(lows)  / len(lows)  if lows  else 0.0

        return ModelPrediction(
            signal=signal,
            confidence=round(confidence, 4),
            direction_up=round(final_up, 4),
            direction_down=round(final_down, 4),
            predicted_high=round(ph, 4),
            predicted_low=round(pl, 4),
        )

    # ── Learning ──────────────────────────────────────────────────────────

    def learn_from_bar(
        self,
        features:     dict,
        label:        int,             # 1 = up, 0 = down
        model_correct: dict[str, bool], # {model_name: was_correct}
    ) -> None:
        for name, correct in model_correct.items():
            if name in self.rolling_accuracy:
                self.rolling_accuracy[name].append(1 if correct else 0)
        try:
            self.user_classifier.learn_one(ml_features(features), label)
        except Exception:
            pass
        self.bar_count += 1

    def learn_from_user_decision(
        self,
        features:    dict,
        user_signal: str,  # "BUY" | "SELL"
        outcome:     int,  # 1 = trade was profitable, 0 = not
    ) -> None:
        """Direct training from the user manually marking a trade outcome."""
        label = 1 if (user_signal == "BUY" and outcome == 1) or \
                     (user_signal == "SELL" and outcome == 0) else 0
        try:
            self.user_classifier.learn_one(ml_features(features), label)
        except Exception:
            pass

    def reset(self) -> None:
        self.user_classifier = linear_model.LogisticRegression(optimizer=optim.SGD(0.05))
        self.bar_count = 0

    def update_settings(self, new_settings: dict) -> None:
        self.settings.update(new_settings)

    def get_settings(self) -> dict:
        return self.settings.copy()
