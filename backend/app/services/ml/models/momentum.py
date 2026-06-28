from river import linear_model, optim
from app.services.ml.models.base import BasePersonalityModel, ModelPrediction


class MomentumModel(BasePersonalityModel):
    """
    Trend follower — signals BUY/SELL only when the EMA stack confirms the
    classifier's direction.  Converts to HOLD when EMAs disagree with classifier.
    """

    name = "momentum"

    def _build_classifier(self):
        return linear_model.LogisticRegression(optimizer=optim.SGD(0.05))

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.62,
            "max_signals_per_session": 20,
            "signal_mode": "balanced",
            "learning_rate": 0.05,
        }

    def predict(self, features: dict, last_close: float, **kwargs) -> ModelPrediction:
        p_up, p_down = self._raw_proba(features)
        ph, pl       = self._raw_targets(features, last_close)
        confidence   = max(p_up, p_down)

        ema9  = features.get("ema_9",  0.0)
        ema21 = features.get("ema_21", 0.0)
        ema50 = features.get("ema_50", 0.0)

        bull_stack = ema9 > ema21 > ema50 > 0
        bear_stack = 0 < ema9 < ema21 < ema50

        if p_up > p_down and bull_stack:
            signal = "BUY"
        elif p_down > p_up and bear_stack:
            signal = "SELL"
        else:
            signal = "HOLD"

        return self._apply_gates(signal, confidence, p_up, p_down, ph, pl)
