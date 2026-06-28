from river import tree
from app.services.ml.models.base import BasePersonalityModel


class ScalperModel(BasePersonalityModel):
    """
    High-frequency scalper — fires often with a low confidence gate.
    Features that matter most: rsi_14, close_position, bar_range.
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
        }
