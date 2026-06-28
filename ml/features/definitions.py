# Shared feature definitions — single source of truth for feature names and computation logic.
# Used by both backend/app/services/market_data/features.py (live computation)
# and any offline backtesting scripts.
# Features: rsi_14, ema_9, ema_21, ema_50, macd, macd_signal, atr_14, volume_delta, bar_range, close_position
# All computed using River rolling stat primitives for memory efficiency.
