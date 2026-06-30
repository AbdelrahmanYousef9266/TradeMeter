"""
Champion/Challenger system for TradeMeter.

Each model runs two River instances simultaneously:
- Champion: currently serving live predictions to dashboard
- Challenger: running silently with mutated hyperparameters

Every EVAL_INTERVAL bars (default 100):
- Compare Champion vs Challenger P&L over the evaluation window
- Winner becomes new Champion
- Loser resets with new random mutations of the winner's params
- Promotion event published to Redis pub/sub → dashboard notification
"""

import random
from dataclasses import dataclass
from typing import Optional
from collections import deque

EVAL_INTERVAL = 100    # bars between evaluations
MUTATION_RATE = 0.15   # ±15% variation per param


def mutate_params(params: dict) -> dict:
    """
    Create a mutated copy of model params.
    Each float value varies by ±MUTATION_RATE.
    Non-numeric params (signal_mode, etc.) are copied unchanged.
    """
    mutated = {}
    for key, value in params.items():
        if isinstance(value, float):
            factor = 1 + random.uniform(-MUTATION_RATE, MUTATION_RATE)
            mutated[key] = round(value * factor, 4)
        else:
            mutated[key] = value

    # Clamp values to safe ranges
    mutated["min_confidence"]  = max(0.50, min(0.90, mutated.get("min_confidence", 0.60)))
    mutated["atr_stop_mult"]   = max(0.5,  min(4.0,  mutated.get("atr_stop_mult",  1.5)))
    mutated["atr_target_mult"] = max(1.0,  min(8.0,  mutated.get("atr_target_mult", 3.0)))
    if "learning_rate" in mutated:
        mutated["learning_rate"] = max(0.01, min(0.30, mutated["learning_rate"]))

    return mutated


@dataclass
class ModelVersion:
    """Tracks P&L stats for one version (Champion or Challenger) of a model."""
    version_id:     str
    model_name:     str
    params:         dict
    bars_evaluated: int   = 0
    pnl_points:     float = 0.0
    trade_count:    int   = 0
    win_count:      int   = 0

    @property
    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count else 0.0

    def record_trade(self, pnl: float, won: bool) -> None:
        self.pnl_points += pnl
        self.trade_count += 1
        if won:
            self.win_count += 1

    def reset_eval_window(self) -> None:
        self.bars_evaluated = 0
        self.pnl_points     = 0.0
        self.trade_count    = 0
        self.win_count      = 0

    def to_dict(self) -> dict:
        return {
            "version_id":     self.version_id,
            "params":         self.params,
            "bars_evaluated": self.bars_evaluated,
            "pnl_points":     round(self.pnl_points, 2),
            "trade_count":    self.trade_count,
            "win_count":      self.win_count,
            "win_rate":       round(self.win_rate, 3),
        }


@dataclass
class PromotionEvent:
    """Fired when a Challenger beats the Champion."""
    model_name:     str
    winner:         str    # "champion" or "challenger"
    champion_pnl:   float
    challenger_pnl: float
    new_params:     dict
    old_params:     dict
    bars_evaluated: int


class ChampionChallenger:
    """
    Manages Champion/Challenger competition for one model for one user.

    The Champion's predictions are what the dashboard sees.
    The Challenger runs silently with mutated params, learning from the same
    trade outcomes. Every EVAL_INTERVAL bars the better P&L wins.
    """

    def __init__(self, model_name: str, base_model_class, initial_params: dict):
        self.model_name       = model_name
        self.base_model_class = base_model_class
        self.eval_interval    = EVAL_INTERVAL
        self.bars_since_eval  = 0

        # Champion
        champion_model = base_model_class()
        champion_model.update_settings(initial_params)
        self._champion_model_obj = champion_model
        self.champion = ModelVersion(
            version_id = "champion",
            model_name = model_name,
            params     = dict(initial_params),
        )

        # Challenger — mutated copy of champion params
        challenger_params = mutate_params(initial_params)
        challenger_model = base_model_class()
        challenger_model.update_settings(challenger_params)
        self._challenger_model_obj = challenger_model
        self.challenger = ModelVersion(
            version_id = "challenger",
            model_name = model_name,
            params     = challenger_params,
        )

        self.promotion_history: deque = deque(maxlen=10)

    def predict(self, features: dict, last_close: float, **kwargs):
        """
        Returns Champion prediction (live).
        Challenger also runs to keep its state warm but result is discarded.
        **kwargs are forwarded to both models (e.g. other_predictions for Contrarian).
        """
        champion_pred = self._champion_model_obj.predict(features, last_close, **kwargs)
        _             = self._challenger_model_obj.predict(features, last_close, **kwargs)

        self.bars_since_eval          += 1
        self.champion.bars_evaluated  += 1
        self.challenger.bars_evaluated += 1

        return champion_pred

    def learn(self, trade_outcome: dict) -> None:
        """
        Called when a simulated trade closes.
        Both Champion and Challenger learn from the same outcome.
        trade_outcome keys: signal, features, pnl_points, won, exit_price, exit_reason
        """
        class _FakeTrade:
            def __init__(self, d):
                self.signal         = d["signal"]
                self.features       = d["features"]
                self.pnl_points     = d["pnl_points"]
                self.exit_price     = d.get("exit_price") or 0.0
                self.exit_reason    = d.get("exit_reason", "target")
                self.won            = d["won"]
                self.direction_label = 1 if d["signal"] == "BUY" else 0

        fake = _FakeTrade(trade_outcome)
        self._champion_model_obj.learn_from_trade(fake)
        self._challenger_model_obj.learn_from_trade(fake)

        # Record P&L for evaluation
        pnl = trade_outcome["pnl_points"]
        won = trade_outcome["won"]
        self.champion.record_trade(pnl, won)
        self.challenger.record_trade(pnl, won)

    def maybe_evaluate(self) -> Optional[PromotionEvent]:
        """
        If EVAL_INTERVAL bars have passed, compare Champion vs Challenger P&L.
        Returns PromotionEvent when Challenger wins, else None.
        """
        if self.bars_since_eval < self.eval_interval:
            return None

        self.bars_since_eval = 0
        champion_pnl   = self.champion.pnl_points
        challenger_pnl = self.challenger.pnl_points

        # Strict greater-than: ties always keep the Champion (stability over churn)
        if challenger_pnl > champion_pnl:
            # Challenger wins — promote it to Champion
            event = PromotionEvent(
                model_name     = self.model_name,
                winner         = "challenger",
                champion_pnl   = champion_pnl,
                challenger_pnl = challenger_pnl,
                new_params     = dict(self.challenger.params),
                old_params     = dict(self.champion.params),
                bars_evaluated = self.eval_interval,
            )

            # Promote challenger: swap model object and params
            old_champion_params = dict(self.champion.params)

            self._champion_model_obj = self._challenger_model_obj
            self.champion = ModelVersion(
                version_id = "champion",
                model_name = self.model_name,
                params     = dict(self.challenger.params),
            )

            # Spawn new challenger with mutations of old champion params
            new_challenger_params = mutate_params(old_champion_params)
            new_challenger_model = self.base_model_class()
            new_challenger_model.update_settings(new_challenger_params)
            self._challenger_model_obj = new_challenger_model
            self.challenger = ModelVersion(
                version_id = "challenger",
                model_name = self.model_name,
                params     = new_challenger_params,
            )

            self.promotion_history.append(event)
            return event

        else:
            # Champion wins — reset challenger with mutations of champion
            new_challenger_params = mutate_params(self.champion.params)
            new_challenger_model = self.base_model_class()
            new_challenger_model.update_settings(new_challenger_params)
            self._challenger_model_obj = new_challenger_model
            self.challenger = ModelVersion(
                version_id = "challenger",
                model_name = self.model_name,
                params     = new_challenger_params,
            )
            self.champion.reset_eval_window()
            self.challenger.reset_eval_window()
            return None

    def get_status(self) -> dict:
        return {
            "model_name":        self.model_name,
            "champion":          self.champion.to_dict(),
            "challenger":        self.challenger.to_dict(),
            "bars_since_eval":   self.bars_since_eval,
            "bars_until_eval":   max(0, self.eval_interval - self.bars_since_eval),
            "eval_interval":     self.eval_interval,
            "promotion_history": [
                {
                    "winner":          e.winner,
                    "champion_pnl":    round(e.champion_pnl, 2),
                    "challenger_pnl":  round(e.challenger_pnl, 2),
                    "new_params":      e.new_params,
                    "old_params":      e.old_params,
                    "bars_evaluated":  e.bars_evaluated,
                }
                for e in self.promotion_history
            ],
        }
