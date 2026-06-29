from river import tree
from app.services.ml.models.base import BasePersonalityModel, ModelPrediction


class MeanReversionModel(BasePersonalityModel):
    """
    Fades extremes — signals BUY only when RSI < oversold threshold,
    SELL only when RSI > overbought threshold.  Silent in normal ranges.
    """

    name = "mean_reversion"

    def _build_classifier(self):
        return tree.HoeffdingTreeClassifier(grace_period=50, delta=1e-5)

    def _default_settings(self) -> dict:
        return {
            "min_confidence": 0.60,
            "max_signals_per_session": 15,
            "signal_mode": "balanced",
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "atr_stop_mult":   1.0,    # tight — mean rev should work fast or not at all
            "atr_target_mult": 2.0,
        }

    def predict(self, features: dict, last_close: float, **kwargs) -> ModelPrediction:
        p_up, p_down = self._raw_proba(features)
        ph, pl       = self._raw_targets(features, last_close)
        confidence   = max(p_up, p_down)

        rsi        = features.get("rsi_14", 50.0)
        overbought = self.settings.get("rsi_overbought", 70)
        oversold   = self.settings.get("rsi_oversold",   30)

        if p_up > p_down and rsi < oversold:
            signal = "BUY"
        elif p_down > p_up and rsi > overbought:
            signal = "SELL"
        else:
            signal = "HOLD"

        # VWAP confirmation: mean reversion against the prevailing VWAP bias is risky
        vwap_dist = features.get("vwap_distance", 0.0)
        if signal == "BUY" and vwap_dist > 0.001:
            # Price already above VWAP — buying into strength undermines mean reversion thesis
            confidence *= 0.7
        if signal == "SELL" and vwap_dist < -0.001:
            # Price already below VWAP — selling into weakness undermines mean reversion thesis
            confidence *= 0.7

        return self._apply_gates(signal, confidence, p_up, p_down, ph, pl)
