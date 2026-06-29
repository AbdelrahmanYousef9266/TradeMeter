"""
Simulated trade tracker for Level 3 P&L learning.

When a model fires BUY or SELL, a simulated trade opens at the next bar's open.
The trade is tracked bar by bar until:
  1. Take profit is hit (price reaches target) → WIN
  2. Stop loss is hit (price reaches stop)    → LOSS
  3. End of session (4:00 PM ET)             → SCRATCH (exit at current price)

The outcome is then fed back to the model as the learning label.
"""

from dataclasses import dataclass
from datetime import time
from typing import Optional

MES_POINT_VALUE = 5.0    # $5 per point per contract
SESSION_END = time(16, 0)  # 4:00 PM ET


def _get_et_time(utc_dt):
    """Return time object in Eastern Time."""
    from app.services.market_data.features import get_et_time
    return get_et_time(utc_dt).time()


@dataclass
class SimulatedTrade:
    """A single simulated trade opened by a model signal."""
    model_name:   str
    user_id:      str
    signal:       str           # "BUY" or "SELL"
    entry_price:  float         # filled at next bar open
    stop_loss:    float         # ATR-based stop
    take_profit:  float         # ATR-based target
    entry_time:   object        # datetime
    confidence:   float
    features:     dict          # features at signal time (for learn_one)

    # Filled when trade closes
    exit_price:   Optional[float] = None
    exit_reason:  Optional[str]   = None   # "target" | "stop" | "timeout"
    pnl_points:   Optional[float] = None   # P&L in MES points
    pnl_dollars:  Optional[float] = None   # P&L in dollars (1 contract)
    bars_held:    int = 0
    is_open:      bool = True

    def update(self, bar_high: float, bar_low: float,
               bar_close: float, bar_time: object) -> bool:
        """
        Check if trade should close on this bar.
        Returns True if trade closed, False if still open.
        """
        if not self.is_open:
            return False

        self.bars_held += 1
        et_time = _get_et_time(bar_time)

        if self.signal == "BUY":
            if bar_high >= self.take_profit:
                self._close(self.take_profit, "target", bar_time)
                return True
            if bar_low <= self.stop_loss:
                self._close(self.stop_loss, "stop", bar_time)
                return True
        elif self.signal == "SELL":
            if bar_low <= self.take_profit:
                self._close(self.take_profit, "target", bar_time)
                return True
            if bar_high >= self.stop_loss:
                self._close(self.stop_loss, "stop", bar_time)
                return True

        if et_time >= SESSION_END:
            self._close(bar_close, "timeout", bar_time)
            return True

        return False

    def _close(self, exit_price: float, reason: str, exit_time: object):
        self.exit_price  = exit_price
        self.exit_reason = reason
        self.is_open     = False

        if self.signal == "BUY":
            self.pnl_points = exit_price - self.entry_price
        else:
            self.pnl_points = self.entry_price - exit_price

        self.pnl_dollars = self.pnl_points * MES_POINT_VALUE

    @property
    def won(self) -> bool:
        """True if trade was profitable after spread cost."""
        spread_cost = 0.25  # 1 tick spread in points
        return (self.pnl_points or 0) > spread_cost

    @property
    def direction_label(self) -> int:
        """1 if BUY, 0 if SELL — for classifier learn_one."""
        return 1 if self.signal == "BUY" else 0

    def to_dict(self) -> dict:
        return {
            "model_name":  self.model_name,
            "signal":      self.signal,
            "entry_price": self.entry_price,
            "exit_price":  self.exit_price,
            "stop_loss":   self.stop_loss,
            "take_profit": self.take_profit,
            "exit_reason": self.exit_reason,
            "pnl_points":  round(self.pnl_points or 0, 2),
            "pnl_dollars": round(self.pnl_dollars or 0, 2),
            "bars_held":   self.bars_held,
            "won":         self.won,
        }


class TradeManager:
    """
    Manages open simulated trades for all models for one user.
    One instance per user, stored alongside the MLPipeline.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.open_trades: dict[str, list[SimulatedTrade]] = {}
        self.closed_trades: list[SimulatedTrade] = []
        self.session_pnl: dict[str, float] = {}
        self._last_session_date = None

    def open_trade(
        self,
        model_name: str,
        signal: str,
        next_bar_open: float,
        atr: float,
        atr_stop_mult: float,
        atr_target_mult: float,
        confidence: float,
        features: dict,
        bar_time: object,
    ) -> Optional[SimulatedTrade]:
        """
        Open a new simulated trade when a model fires a non-HOLD signal.
        stop_loss   = entry ± (atr × atr_stop_mult)
        take_profit = entry ± (atr × atr_target_mult)
        """
        if signal == "HOLD":
            return None

        stop_dist   = atr * atr_stop_mult
        target_dist = atr * atr_target_mult

        if signal == "BUY":
            stop_loss   = next_bar_open - stop_dist
            take_profit = next_bar_open + target_dist
        else:  # SELL
            stop_loss   = next_bar_open + stop_dist
            take_profit = next_bar_open - target_dist

        trade = SimulatedTrade(
            model_name  = model_name,
            user_id     = self.user_id,
            signal      = signal,
            entry_price = next_bar_open,
            stop_loss   = stop_loss,
            take_profit = take_profit,
            entry_time  = bar_time,
            confidence  = confidence,
            features    = features,
        )

        if model_name not in self.open_trades:
            self.open_trades[model_name] = []
        self.open_trades[model_name].append(trade)
        return trade

    def update_all(
        self,
        bar_high: float,
        bar_low: float,
        bar_close: float,
        bar_time: object,
    ) -> list[SimulatedTrade]:
        """
        Update all open trades with new bar data.
        Returns list of trades that closed this bar.
        """
        from app.services.market_data.features import get_et_time
        et = get_et_time(bar_time)
        bar_date = et.date()
        if self._last_session_date != bar_date:
            self._last_session_date = bar_date
            self.session_pnl = {}

        newly_closed = []

        for model_name, trades in self.open_trades.items():
            still_open = []
            for trade in trades:
                closed = trade.update(bar_high, bar_low, bar_close, bar_time)
                if closed:
                    newly_closed.append(trade)
                    self.closed_trades.append(trade)
                    self.session_pnl[model_name] = (
                        self.session_pnl.get(model_name, 0.0) + (trade.pnl_points or 0)
                    )
                else:
                    still_open.append(trade)
            self.open_trades[model_name] = still_open

        return newly_closed

    def get_session_pnl(self) -> dict[str, float]:
        """Returns today's P&L in points per model."""
        return dict(self.session_pnl)

    def pop_closed_trades(self) -> list[SimulatedTrade]:
        """Returns and clears the closed trades queue."""
        trades = list(self.closed_trades)
        self.closed_trades = []
        return trades
