"""
Feature engine — computes 10 technical indicators from OHLCV bars.

One FeatureEngine instance per user keeps rolling state between bars.
All statistics update in O(1) per bar using exponential smoothing.
Returns None during the 50-bar warmup period.
"""

from collections import deque
from app.models.tick import Tick


class _EMA:
    """Standard exponential moving average with alpha = 2/(period+1)."""

    def __init__(self, period: int) -> None:
        self._alpha = 2.0 / (period + 1)
        self._value: float | None = None

    def update(self, x: float) -> None:
        if self._value is None:
            self._value = x
        else:
            self._value = self._alpha * x + (1.0 - self._alpha) * self._value

    def get(self) -> float | None:
        return self._value


class _WilderEMA:
    """
    Wilder smoothing: alpha = 1/period.
    Used for RSI (avg gain/loss) and ATR — both defined with Wilder's method.
    """

    def __init__(self, period: int) -> None:
        self._alpha = 1.0 / period
        self._value: float | None = None

    def update(self, x: float) -> None:
        if self._value is None:
            self._value = x
        else:
            self._value = self._alpha * x + (1.0 - self._alpha) * self._value

    def get(self) -> float | None:
        return self._value


class FeatureEngine:
    """
    Stateful feature computer — keep one instance alive per user between bars.
    Call update(bar) on every bar close (bar_type != 'tick').
    """

    def __init__(self) -> None:
        self._bar_count: int = 0
        self._prev_close: float | None = None

        # Price EMAs
        self._ema_9  = _EMA(9)
        self._ema_12 = _EMA(12)
        self._ema_21 = _EMA(21)
        self._ema_26 = _EMA(26)
        self._ema_50 = _EMA(50)

        # MACD signal line: EMA(9) of the MACD line itself
        self._macd_signal_ema = _EMA(9)

        # RSI components: Wilder smoothing of average gain and average loss
        self._avg_gain = _WilderEMA(14)
        self._avg_loss = _WilderEMA(14)

        # ATR: Wilder smoothing of true range
        self._atr = _WilderEMA(14)

        # Volume: 20-bar simple rolling average via deque
        self._vol_window: deque[float] = deque(maxlen=20)

    def update(self, bar: Tick) -> dict | None:
        """
        Update all rolling stats with bar and return the feature dict.
        Returns None for the first 49 bars (insufficient history for EMA-50).
        """
        self._bar_count += 1

        close = bar.close
        high  = bar.high
        low   = bar.low
        vol   = float(bar.volume)

        # ── Price EMAs ──────────────────────────────────────────────────────
        self._ema_9.update(close)
        self._ema_12.update(close)
        self._ema_21.update(close)
        self._ema_26.update(close)
        self._ema_50.update(close)

        # ── MACD line and signal line ────────────────────────────────────────
        macd = (self._ema_12.get() or 0.0) - (self._ema_26.get() or 0.0)
        self._macd_signal_ema.update(macd)

        # ── RSI ─────────────────────────────────────────────────────────────
        if self._prev_close is not None:
            change = close - self._prev_close
            gain   = max(change, 0.0)
            loss   = abs(min(change, 0.0))
            self._avg_gain.update(gain)
            self._avg_loss.update(loss)

        # ── ATR (true range) ─────────────────────────────────────────────────
        if self._prev_close is not None:
            true_range = max(
                high - low,
                abs(high - self._prev_close),
                abs(low  - self._prev_close),
            )
        else:
            true_range = high - low
        self._atr.update(true_range)

        # ── Volume rolling mean ──────────────────────────────────────────────
        self._vol_window.append(vol)

        self._prev_close = close

        # Warmup: need 50 bars before EMA-50 and other indicators are meaningful
        if self._bar_count < 50:
            return None

        # ── Compute RSI ──────────────────────────────────────────────────────
        avg_gain = self._avg_gain.get() or 0.0
        avg_loss = self._avg_loss.get() or 0.0
        if avg_loss == 0.0:
            rsi = 100.0
        else:
            rsi = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

        # ── Volume delta ─────────────────────────────────────────────────────
        vol_mean = sum(self._vol_window) / len(self._vol_window)
        volume_delta = (vol / vol_mean - 1.0) if vol_mean > 0 else 0.0

        # ── Bar geometry ─────────────────────────────────────────────────────
        bar_range = high - low
        if bar_range > 0:
            close_position = (close - low) / bar_range
        else:
            close_position = 0.5  # doji / gap — midpoint by convention

        return {
            "rsi_14":       round(rsi, 4),
            "ema_9":        round(self._ema_9.get() or 0.0,  4),
            "ema_21":       round(self._ema_21.get() or 0.0, 4),
            "ema_50":       round(self._ema_50.get() or 0.0, 4),
            "macd":         round(macd, 4),
            "macd_signal":  round(self._macd_signal_ema.get() or 0.0, 4),
            "atr_14":       round(self._atr.get() or 0.0, 4),
            "volume_delta": round(volume_delta, 4),
            "bar_range":    round(bar_range, 4),
            "close_position": round(close_position, 4),
        }


# ── Global registry ────────────────────────────────────────────────────────

_engines: dict[str, FeatureEngine] = {}


def get_engine(user_id: str) -> FeatureEngine:
    """Return the FeatureEngine for this user, creating one if it doesn't exist."""
    if user_id not in _engines:
        _engines[user_id] = FeatureEngine()
    return _engines[user_id]
