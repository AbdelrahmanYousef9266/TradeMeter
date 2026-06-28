from river import tree
from app.services.ml.models.base import BasePersonalityModel, ModelPrediction


class BreakoutModel(BasePersonalityModel):
    """
    Range-expansion hunter — requires both a volume spike AND a wide bar
    (relative to ATR) before considering a signal.  Stays silent otherwise.
    """

    name = "breakout"

    def _build_classifier(self):
        return tree.HoeffdingTreeClassifier(grace_period=50, delta=1e-5)

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.63,
            "max_signals_per_session": 12,
            "signal_mode": "balanced",
            "volume_spike_threshold": 1.8,
            "atr_multiplier": 1.5,
        }

    def predict(self, features: dict, last_close: float, **kwargs) -> ModelPrediction:
        p_up, p_down = self._raw_proba(features)
        ph, pl       = self._raw_targets(features, last_close)
        confidence   = max(p_up, p_down)

        vol_delta = features.get("volume_delta", 0.0)
        bar_range = features.get("bar_range",    0.0)
        atr       = features.get("atr_14",       0.0)

        vol_thresh = self.settings.get("volume_spike_threshold", 1.8)
        atr_mult   = self.settings.get("atr_multiplier", 1.5)

        has_volume_spike    = vol_delta > vol_thresh
        has_range_expansion = (bar_range > atr * atr_mult) if atr > 0 else False

        if not (has_volume_spike and has_range_expansion):
            signal = "HOLD"
        elif p_up > p_down:
            signal = "BUY"
        else:
            signal = "SELL"

        return self._apply_gates(signal, confidence, p_up, p_down, ph, pl)
