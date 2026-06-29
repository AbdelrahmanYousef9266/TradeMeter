from river import linear_model, optim
from app.services.ml.models.base import BasePersonalityModel, ModelPrediction


class AggressiveModel(BasePersonalityModel):
    """
    High-frequency, low threshold, wide price targets.
    Uses target_multiplier to scale predicted high/low further from current price.
    """

    name = "aggressive"

    def _build_classifier(self):
        return linear_model.LogisticRegression(optimizer=optim.SGD(0.12))

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.51,
            "max_signals_per_session": 50,
            "signal_mode": "aggressive",
            "learning_rate": 0.12,
            "target_multiplier": 2.0,
            "atr_stop_mult":   2.5,    # wide stop
            "atr_target_mult": 6.0,    # very wide target
        }

    def predict(self, features: dict, last_close: float, **kwargs) -> ModelPrediction:
        pred = super().predict(features, last_close)
        # Widen targets by the multiplier so this model shoots for bigger moves
        mult = self.settings.get("target_multiplier", 2.0)
        mid  = (pred.predicted_high + pred.predicted_low) / 2
        half = (pred.predicted_high - pred.predicted_low) / 2 * mult
        return ModelPrediction(
            signal=pred.signal,
            confidence=pred.confidence,
            direction_up=pred.direction_up,
            direction_down=pred.direction_down,
            predicted_high=mid + half,
            predicted_low=mid - half,
        )
