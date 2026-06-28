from river import naive_bayes
from app.services.ml.models.base import BasePersonalityModel


class ConservativeModel(BasePersonalityModel):
    """
    Low-risk, high-conviction only — 75 % confidence floor means it mostly HOLDs.
    When it does fire it should be the most reliable signal on the board.
    """

    name = "conservative"

    def _build_classifier(self):
        return naive_bayes.GaussianNB()

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.75,
            "max_signals_per_session": 8,
            "signal_mode": "conservative",
            "learning_rate": 0.03,
        }
