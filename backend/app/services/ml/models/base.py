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


def ml_features(features: dict) -> dict:
    """
    Strip metadata keys (those prefixed with '_', e.g. _close) before passing a
    feature dict to a River model.  Metadata rides alongside the 16 real features
    for bookkeeping (ATR-relative target conversion) but must NEVER be trained on
    — a raw price like _close would dominate a linear regressor.
    """
    return {k: v for k, v in features.items() if not k.startswith("_")}


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

    # ATR multipliers — each model overrides these in _default_settings
    DEFAULT_ATR_STOP_MULT   = 1.5   # stop = entry ± ATR × 1.5
    DEFAULT_ATR_TARGET_MULT = 3.0   # target = entry ± ATR × 3.0 (2:1 R:R)

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
            proba = self.classifier.predict_proba_one(ml_features(features))
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
        """
        Return (predicted_high, predicted_low) as absolute prices.

        The regressors predict ATR-relative *offsets* — how many ATRs the high
        sits above / the low sits below the current close — not absolute prices.
        Linear regression on raw prices extrapolates wildly (a next-bar target
        45 % above spot); offsets stay bounded.  Offsets are clamped to 0.5–5 ATR
        and converted back to absolute prices here.
        """
        atr = features.get("atr_14") or 1.0
        if atr <= 0:
            atr = 1.0

        ml = ml_features(features)
        try:
            high_off = self.regressor_high.predict_one(ml)
            low_off  = self.regressor_low.predict_one(ml)
        except Exception:
            high_off = low_off = None

        # Untrained regressors return 0.0 → fall back to a 2-ATR default.
        high_off = max(0.5, min(high_off if high_off else 2.0, 5.0))
        low_off  = max(0.5, min(low_off  if low_off  else 2.0, 5.0))

        ph = last_close + high_off * atr
        pl = last_close - low_off  * atr
        return round(ph, 2), round(pl, 2)

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
        """
        Update classifier (direction) and regressors (price targets).

        Regressor targets are ATR-relative offsets, not absolute prices:
          high_offset = (label_high - close) / atr   (ATRs above close)
          low_offset  = (close - label_low) / atr    (ATRs below close)
        clamped to 0–5 ATR so a single outlier bar can't blow up the weights.
        """
        ml = ml_features(features)
        try:
            self.classifier.learn_one(ml, label_direction)
        except Exception:
            pass

        close = features.get("_close") or features.get("close")
        atr   = features.get("atr_14") or 1.0
        if atr <= 0:
            atr = 1.0
        if close:
            high_off = max(0.0, min((label_high - close) / atr, 5.0))
            low_off  = max(0.0, min((close - label_low) / atr, 5.0))
            try:
                self.regressor_high.learn_one(ml, high_off)
                self.regressor_low.learn_one(ml, low_off)
            except Exception:
                pass
        self.bar_count += 1

    def learn_from_trade(self, trade) -> None:
        """
        Level 3 learning — called when a simulated trade closes.
        Uses actual P&L outcome as the training signal instead of a direction label.

        Timeout (scratch) skips learning — neither right nor wrong.
        Won trade: reinforce predicted direction. Lost trade: penalize.
        """
        if trade.exit_reason == "timeout":
            return

        label = trade.direction_label if trade.won else 1 - trade.direction_label

        # Magnitude weight (bigger P&L relative to ATR = stronger signal)
        atr = trade.features.get("atr_14") or 1.0
        if atr <= 0:
            atr = 1.0
        magnitude = abs(trade.pnl_points or 0) / max(atr, 0.01)
        weight = min(magnitude, 3.0)  # cap at 3× to prevent outlier dominance

        ml = ml_features(trade.features)
        try:
            self.classifier.learn_one(ml, label)
        except Exception:
            pass

        # Train the relevant regressor on the realized exit distance as an
        # ATR-relative offset from the close at signal time (never absolute
        # price — that extrapolates wildly). Clamped to 0–5 ATR.
        close = trade.features.get("_close") or trade.features.get("close")
        if close:
            try:
                if trade.signal == "BUY":
                    off = max(0.0, min((trade.exit_price - close) / atr, 5.0))
                    self.regressor_high.learn_one(ml, off)
                else:
                    off = max(0.0, min((close - trade.exit_price) / atr, 5.0))
                    self.regressor_low.learn_one(ml, off)
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
