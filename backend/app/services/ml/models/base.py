"""
Base class for all 8 personality models.

Each subclass provides:
  _build_classifier() → River classifier with predict_proba_one()
  _default_settings() → dict of behavior parameters

predict() and learn() are final — personality-specific gating logic
should override predict() and call _base_predict() for the raw probabilities.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ModelPrediction:
    signal:         str    # "BUY" | "SELL" | "HOLD"
    confidence:     float  # max(direction_up, direction_down)
    direction_up:   float  # probability 0.0–1.0
    direction_down: float  # probability 0.0–1.0
    predicted_high: float
    predicted_low:  float


class BasePersonalityModel(ABC):
    """
    Template for personality models.  River classifiers and regressors are
    synchronous — never use async/await here.
    """

    name: str = "base"

    def __init__(self) -> None:
        self.classifier     = self._build_classifier()
        self.regressor_high = self._build_regressor()
        self.regressor_low  = self._build_regressor()
        self.settings       = self._default_settings()
        self.bar_count      = 0
        self._session_signal_count = 0

    # ── Abstract ──────────────────────────────────────────────────────────

    @abstractmethod
    def _build_classifier(self):
        """Return a River classifier that supports predict_proba_one()."""
        ...

    @abstractmethod
    def _default_settings(self) -> dict:
        """Return default behavior settings for this personality."""
        ...

    # ── Regressor ─────────────────────────────────────────────────────────

    def _build_regressor(self):
        from river import linear_model, preprocessing
        return preprocessing.StandardScaler() | linear_model.LinearRegression()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _raw_proba(self, features: dict) -> tuple[float, float]:
        """
        Return (p_up, p_down) from the classifier.
        Handles untrained classifiers safely.
        """
        try:
            proba = self.classifier.predict_proba_one(features)
            p_up   = proba.get(1, 0.5) if proba else 0.5
            p_down = proba.get(0, 0.5) if proba else 0.5
        except Exception:
            p_up, p_down = 0.5, 0.5
        # Normalize in case probabilities don't sum to 1
        total = p_up + p_down
        if total > 0:
            p_up, p_down = p_up / total, p_down / total
        else:
            p_up = p_down = 0.5
        return p_up, p_down

    def _raw_targets(self, features: dict, last_close: float) -> tuple[float, float]:
        """Return (predicted_high, predicted_low) from the regressors."""
        try:
            ph = self.regressor_high.predict_one(features) or 0.0
            pl = self.regressor_low.predict_one(features)  or 0.0
        except Exception:
            ph, pl = 0.0, 0.0
        # Fall back to ±0.1 % of last close if regressors are untrained
        if ph == 0.0 or ph < last_close * 0.98:
            ph = last_close * 1.001
        if pl == 0.0 or pl > last_close * 1.02:
            pl = last_close * 0.999
        return ph, pl

    def _apply_gates(
        self,
        signal: str,
        confidence: float,
        p_up: float,
        p_down: float,
        ph: float,
        pl: float,
    ) -> ModelPrediction:
        """Apply min_confidence and max_signals_per_session gates."""
        min_conf   = self.settings.get("min_confidence", 0.55)
        max_sigs   = self.settings.get("max_signals_per_session", 20)

        if signal != "HOLD":
            if confidence < min_conf:
                signal = "HOLD"
            elif self._session_signal_count >= max_sigs:
                signal = "HOLD"
            else:
                self._session_signal_count += 1

        return ModelPrediction(
            signal=signal,
            confidence=confidence,
            direction_up=p_up,
            direction_down=p_down,
            predicted_high=ph,
            predicted_low=pl,
        )

    # ── Public API ────────────────────────────────────────────────────────

    def predict(self, features: dict, last_close: float, **kwargs) -> ModelPrediction:
        """Default predict — subclasses may override for personality-specific gating."""
        p_up, p_down = self._raw_proba(features)
        ph, pl       = self._raw_targets(features, last_close)
        confidence   = max(p_up, p_down)

        signal = "HOLD" if p_up == p_down else ("BUY" if p_up > p_down else "SELL")
        return self._apply_gates(signal, confidence, p_up, p_down, ph, pl)

    def learn(
        self,
        features:        dict,
        label_direction: int,   # 1 = closed up, 0 = closed down
        label_high:      float,
        label_low:       float,
    ) -> None:
        """Update classifier and regressors with the bar's true outcome."""
        try:
            self.classifier.learn_one(features, label_direction)
        except Exception:
            pass
        try:
            self.regressor_high.learn_one(features, label_high)
        except Exception:
            pass
        try:
            self.regressor_low.learn_one(features, label_low)
        except Exception:
            pass
        self.bar_count += 1

    def reset(self) -> None:
        """Reinitialise weights (called on drift detection)."""
        self.classifier     = self._build_classifier()
        self.regressor_high = self._build_regressor()
        self.regressor_low  = self._build_regressor()
        self.bar_count      = 0
        self._session_signal_count = 0

    def reset_session(self) -> None:
        """Reset per-session counters at the start of each RTH session."""
        self._session_signal_count = 0

    def update_settings(self, new_settings: dict) -> None:
        self.settings.update(new_settings)

    def get_settings(self) -> dict:
        return self.settings.copy()
