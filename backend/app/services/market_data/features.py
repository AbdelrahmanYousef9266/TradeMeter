"""
Feature engine — computes 16 technical indicators from OHLCV bars.

One FeatureEngine instance per user keeps rolling state between bars.
All indicators update in O(1) per bar.
Returns None during the 50-bar warmup period.

Features (16 total):
  Original 10: rsi_14, ema_9, ema_21, ema_50, macd, macd_signal,
               atr_14, volume_delta, bar_range, close_position
  VWAP 3:     vwap, vwap_distance, vwap_cross
  Time 3:     session_minutes, session_phase, is_power_hour
"""

from collections import deque
from datetime import timedelta

from app.models.tick import Tick


# ── Eastern Time helper ────────────────────────────────────────────────────

def _to_et(utc_dt):
    """
    Convert a UTC-aware datetime to Eastern Time.
    Approximates DST: April–October = EDT (UTC-4), otherwise EST (UTC-5).
    Accurate enough for US equity market hours (closed weekends + holidays).
    """
    offset = timedelta(hours=-4) if 4 <= utc_dt.month <= 10 else timedelta(hours=-5)
    return utc_dt + offset


# Public alias used by trade_tracker and any future callers
get_et_time = _to_et


# ── Constants ──────────────────────────────────────────────────────────────

_WARMUP_BARS     = 50
_SESSION_MINUTES = 390   # 9:30 AM to 4:00 PM ET
_MARKET_OPEN_MIN = 9 * 60 + 30   # 570 minutes from midnight ET


# ── Feature engine ─────────────────────────────────────────────────────────

class FeatureEngine:
    """
    Stateful feature computer — keep one instance alive per user between bars.
    Call update(bar) on every bar close (bar_type != 'tick').
    """

    def __init__(self) -> None:
        self.bar_count: int = 0

        # Price EMAs
        self._ema9:  float | None = None
        self._ema12: float | None = None   # for MACD
        self._ema21: float | None = None
        self._ema26: float | None = None   # for MACD
        self._ema50: float | None = None

        # MACD signal: EMA(9) of MACD line
        self._macd_signal: float | None = None

        # RSI: Wilder smoothing of avg gain / avg loss
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None

        # ATR: Wilder smoothing of true range
        self._atr: float | None = None

        # Previous close — needed for ATR, RSI change, VWAP cross
        self._prev_close: float | None = None

        # Volume rolling baseline
        self._vol_window: deque[float] = deque(maxlen=20)

        # VWAP session state — resets each trading day
        self._vwap_date       = None
        self._vwap_cum_pv:  float = 0.0   # cumulative (typical_price × volume)
        self._vwap_cum_vol: float = 0.0   # cumulative volume

    # ── EMA helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _ema(prev: float | None, value: float, period: int) -> float:
        if prev is None:
            return value
        alpha = 2.0 / (period + 1)
        return alpha * value + (1.0 - alpha) * prev

    @staticmethod
    def _wilder(prev: float | None, value: float, period: int) -> float:
        """Wilder's smoothing (RSI, ATR): alpha = 1/period."""
        if prev is None:
            return value
        return (prev * (period - 1) + value) / period

    # ── VWAP ───────────────────────────────────────────────────────────────

    def _update_vwap(self, bar_time, high: float, low: float, close: float, volume: float) -> float:
        """
        Update cumulative VWAP for the current session.
        Resets automatically at the start of each new trading day.
        Uses typical price: (high + low + close) / 3.
        """
        et      = _to_et(bar_time)
        bar_date = et.date()

        if self._vwap_date != bar_date:
            self._vwap_date    = bar_date
            self._vwap_cum_pv  = 0.0
            self._vwap_cum_vol = 0.0

        typical = (high + low + close) / 3.0
        self._vwap_cum_pv  += typical * volume
        self._vwap_cum_vol += volume

        return self._vwap_cum_pv / self._vwap_cum_vol if self._vwap_cum_vol > 0 else close

    # ── Time-of-day ────────────────────────────────────────────────────────

    @staticmethod
    def _time_features(bar_time) -> tuple[int, float, float]:
        """
        Returns (session_minutes, session_phase, is_power_hour) in ET.
        session_minutes: 0 at 9:30 AM ET, 390 at 4:00 PM ET.
        """
        et  = _to_et(bar_time)
        bar_min = et.hour * 60 + et.minute

        session_minutes = max(0, min(bar_min - _MARKET_OPEN_MIN, _SESSION_MINUTES))
        session_phase   = session_minutes / _SESSION_MINUTES

        is_power_hour = 1.0 if 15 * 60 <= bar_min < 16 * 60 else 0.0

        return session_minutes, round(session_phase, 4), is_power_hour

    # ── Main update ────────────────────────────────────────────────────────

    def update(self, bar: Tick) -> dict | None:
        """
        Update all rolling stats with bar and return the feature dict.
        Returns None for the first 49 bars (insufficient history for EMA-50).
        """
        close    = bar.close
        high     = bar.high
        low      = bar.low
        volume   = float(bar.volume)
        bar_time = bar.time

        # ── EMAs ────────────────────────────────────────────────────────
        self._ema9  = self._ema(self._ema9,  close,  9)
        self._ema12 = self._ema(self._ema12, close, 12)
        self._ema21 = self._ema(self._ema21, close, 21)
        self._ema26 = self._ema(self._ema26, close, 26)
        self._ema50 = self._ema(self._ema50, close, 50)

        macd_line        = (self._ema12 or close) - (self._ema26 or close)
        self._macd_signal = self._ema(self._macd_signal, macd_line, 9)

        # ── RSI ─────────────────────────────────────────────────────────
        if self._prev_close is not None:
            change = close - self._prev_close
            gain   = max(change, 0.0)
            loss   = max(-change, 0.0)
            self._avg_gain = self._wilder(self._avg_gain, gain, 14)
            self._avg_loss = self._wilder(self._avg_loss, loss, 14)

        if self._avg_loss is None or self._avg_loss == 0.0:
            rsi = 100.0 if (self._avg_gain or 0.0) > 0 else 50.0
        else:
            rs  = (self._avg_gain or 0.0) / self._avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # ── ATR ─────────────────────────────────────────────────────────
        if self._prev_close is not None:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        else:
            tr = high - low
        self._atr = self._wilder(self._atr, tr, 14)

        # ── Volume baseline ──────────────────────────────────────────────
        self._vol_window.append(volume)
        avg_vol      = sum(self._vol_window) / len(self._vol_window)
        volume_delta = (volume / avg_vol - 1.0) if avg_vol > 0 else 0.0

        # ── Bar geometry ─────────────────────────────────────────────────
        bar_range      = high - low
        close_position = (close - low) / bar_range if bar_range > 0 else 0.5

        # ── VWAP ─────────────────────────────────────────────────────────
        vwap          = self._update_vwap(bar_time, high, low, close, volume)
        vwap_distance = (close - vwap) / vwap if vwap > 0 else 0.0

        # VWAP cross: 1.0 = crossed up, -1.0 = crossed down, 0.0 = no cross
        vwap_cross = 0.0
        if self._prev_close is not None:
            prev_above = self._prev_close >= vwap
            curr_above = close           >= vwap
            if not prev_above and curr_above:
                vwap_cross =  1.0
            elif prev_above and not curr_above:
                vwap_cross = -1.0

        # ── Time of day ───────────────────────────────────────────────────
        session_minutes, session_phase, is_power_hour = self._time_features(bar_time)

        # ── Advance state ─────────────────────────────────────────────────
        self._prev_close = close
        self.bar_count  += 1

        if self.bar_count < _WARMUP_BARS:
            return None

        return {
            # Original 10
            "rsi_14":         round(rsi,          4),
            "ema_9":          round(self._ema9,    4),
            "ema_21":         round(self._ema21,   4),
            "ema_50":         round(self._ema50,   4),
            "macd":           round(macd_line,     4),
            "macd_signal":    round(self._macd_signal or 0.0, 4),
            "atr_14":         round(self._atr or 0.0, 4),
            "volume_delta":   round(volume_delta,  4),
            "bar_range":      round(bar_range,     4),
            "close_position": round(close_position, 4),
            # VWAP (3 new)
            "vwap":           round(vwap,          4),
            "vwap_distance":  round(vwap_distance, 6),
            "vwap_cross":     vwap_cross,
            # Time of day (3 new)
            "session_minutes": session_minutes,
            "session_phase":   session_phase,
            "is_power_hour":   is_power_hour,
            # Metadata (leading '_' → excluded from ML training, see ml_features()).
            # Carried so models can convert ATR-relative target offsets ↔ prices.
            "_close":          close,
        }


# ── Global registry ────────────────────────────────────────────────────────

_engines: dict[str, FeatureEngine] = {}


def get_engine(user_id: str) -> FeatureEngine:
    """Return the FeatureEngine for this user, creating one if it doesn't exist."""
    if user_id not in _engines:
        _engines[user_id] = FeatureEngine()
    return _engines[user_id]
