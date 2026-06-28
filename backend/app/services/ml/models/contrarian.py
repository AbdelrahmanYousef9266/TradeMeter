from river import linear_model, optim
from app.services.ml.models.base import BasePersonalityModel, ModelPrediction


class ContrarianModel(BasePersonalityModel):
    """
    Bets against the crowd.

    When 5+ of the other 7 models agree on BUY → signals SELL (and vice versa).
    If models are split or other_predictions is not provided → uses own classifier.
    Always uses own classifier for the confidence score.
    """

    name = "contrarian"

    def _build_classifier(self):
        return linear_model.LogisticRegression(optimizer=optim.SGD(0.05))

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.58,
            "max_signals_per_session": 15,
            "signal_mode": "balanced",
            "learning_rate": 0.05,
            "consensus_threshold": 5,   # how many models must agree to trigger inversion
        }

    def predict(
        self,
        features: dict,
        last_close: float,
        other_predictions: dict | None = None,
        **kwargs,
    ) -> ModelPrediction:
        p_up, p_down = self._raw_proba(features)
        ph, pl       = self._raw_targets(features, last_close)
        confidence   = max(p_up, p_down)

        if other_predictions:
            signals    = [p.signal for p in other_predictions.values()]
            buys       = signals.count("BUY")
            sells      = signals.count("SELL")
            total      = len(signals)
            threshold  = self.settings.get("consensus_threshold", 5)

            if buys >= threshold:
                # Majority bullish → Contrarian bets down.
                # Confidence is the larger of the consensus ratio and the classifier's
                # own confidence, so a strong crowd signal can override an untrained
                # classifier's neutral 0.50.
                consensus_confidence = buys / total if total else confidence
                final_confidence = max(confidence, consensus_confidence)
                return self._apply_gates("SELL", final_confidence, p_down, p_up, ph, pl)
            elif sells >= threshold:
                # Majority bearish → Contrarian bets up
                consensus_confidence = sells / total if total else confidence
                final_confidence = max(confidence, consensus_confidence)
                return self._apply_gates("BUY", final_confidence, p_up, p_down, ph, pl)
            else:
                # No consensus → HOLD
                return ModelPrediction("HOLD", confidence, p_up, p_down, ph, pl)

        # No other predictions supplied — fall back to own classifier
        return super().predict(features, last_close)
