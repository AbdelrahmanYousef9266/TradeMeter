from river import tree
from app.services.ml.models.base import BasePersonalityModel


class VolumeModel(BasePersonalityModel):
    """
    Order-flow based — dominant features: volume_delta, rsi_14, close_position.
    Configurable spike_threshold and delta_imbalance_cutoff let power users tune
    how aggressively it chases institutional volume bursts.
    """

    name = "volume"

    def _build_classifier(self):
        return tree.HoeffdingTreeClassifier(grace_period=100, delta=1e-5)

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.60,
            "max_signals_per_session": 20,
            "signal_mode": "balanced",
            "volume_spike_threshold": 1.8,
            "delta_imbalance_cutoff": 0.60,
            "lookback_window": 20,
        }
