from river import tree
from app.services.ml.models.base import BasePersonalityModel, ModelPrediction


class ScalperModel(BasePersonalityModel):
    """
    High-frequency scalper — fires often with a low confidence gate.
    Features that matter most: rsi_14, close_position, bar_range.
    Reduces confidence during the 11:30 AM–2:00 PM ET lunch chop window.
    """

    name = "scalper"

    def _build_classifier(self):
        return tree.HoeffdingTreeClassifier(grace_period=50, delta=1e-5)

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.52,
            "max_signals_per_session": 40,
            "signal_mode": "aggressive",
            "learning_rate": 0.10,
            "atr_stop_mult":   0.8,    # tight stop — quick in, quick out
            "atr_target_mult": 1.2,    # small target
        }

    def predict(self, features: dict, last_close: float, **kwargs) -> ModelPrediction:
        p_up, p_down = self._raw_proba(features)
        ph, pl       = self._raw_targets(features, last_close)
        confidence   = max(p_up, p_down)

        # Lunch chop (11:30 AM–2:00 PM ET = session minutes 120–270) has lower
        # volume and more false signals; reduce confidence to filter noise.
        session_minutes = features.get("session_minutes", 200)
        if 120 <= session_minutes <= 270:
            confidence *= 0.75

        signal = "HOLD" if p_up == p_down else ("BUY" if p_up > p_down else "SELL")
        return self._apply_gates(signal, confidence, p_up, p_down, ph, pl)
