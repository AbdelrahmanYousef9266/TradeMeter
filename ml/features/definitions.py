# Shared feature definitions — single source of truth for feature names and computation.
# Used by backend/app/services/market_data/features.py (live) and offline backtesting.
# Features: rsi_14, ema_9, ema_21, ema_50, macd, macd_signal, atr_14,
#           volume_delta, bar_range, close_position
# XP label features (computed after bar closes, used by level system):
#   - direction_correct: bool (predicted up/down matched actual close direction)
#   - pnl_delta: float (bar P&L change vs previous bar)
# All features computed using River rolling stat primitives.
