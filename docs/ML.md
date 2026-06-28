# ML Pipeline

## Overview

TradeMeter runs **10 parallel incremental ML models** using the River library. All 10 models receive the same feature vector on every bar close. Each model independently calls `.predict_one()` to generate its signal, then `.learn_one()` when the next bar's actual outcome is known. No model shares weights with any other. No historical dataset is stored. No retraining jobs are scheduled.

All models output three values per bar: **direction** (up/down probability), **price target** (predicted high and low), and **signal** (BUY / SELL / HOLD with confidence %).

---

## Model Table

| # | Name | Personality | River Algorithm | Signal style |
|---|------|-------------|-----------------|--------------|
| 1 | Scalper | Ultra short-term, high frequency | HoeffdingTreeClassifier | Aggressive — many signals, tight targets |
| 2 | Momentum | Trend follower | LogisticRegression | Medium — EMA cross driven |
| 3 | Mean Reversion | Fades extremes | HoeffdingTreeClassifier | Medium — RSI extreme driven |
| 4 | Breakout Hunter | Breakout entries | HoeffdingTreeClassifier | Medium — ATR/volume spike driven |
| 5 | Conservative | Low risk, small moves | GaussianNaiveBayes | Rare — 75%+ confidence required |
| 6 | Aggressive | High risk, big moves | LogisticRegression | Frequent — 50% threshold |
| 7 | Volume | Order flow based | HoeffdingTreeClassifier | Medium — volume delta dominant |
| 8 | Contrarian | Bets against the crowd | LogisticRegression | Inverts majority consensus |
| 9 | You (personal) | Your personal hybrid | Ensemble (blends 1-8) | Shifts toward current best performers |
| 10 | Brother (personal) | Brother's personal hybrid | Ensemble (blends 1-8) | Separate weights, same blend logic |

---

## Personal Models (9 and 10)

Models 9 and 10 are instances of the same `PersonalModel` class, scoped by `user_id`.

**Blend weight computation (runs on every bar):**
1. Compute rolling 50-bar accuracy for each of models 1-8
2. Normalize accuracies to sum to 1.0 → these become blend weights
3. If the user has set manual overrides in ModelSettings, apply them on top (user overrides clamp and renormalize)
4. Final signal = weighted average of models 1-8 predictions using computed weights

**Learning from trading decisions:**
When a user manually marks a trade outcome in the dashboard, the personal model calls `.learn_one()` with that label, independent of the bar-close label. This lets the personal model learn which signals the user actually acted on and how those resolved.

**Independence:** Model 9 (your account) and Model 10 (brother's account) have completely independent blend weights, learning histories, and manual overrides. They happen to use the same code class but nothing is shared between them.

---

## Features

Ten features are computed from raw OHLCV data by `features.py` before being passed to any model:

| Feature | Description |
|---|---|
| `rsi_14` | RSI(14) computed incrementally using River's rolling mean |
| `ema_9` | Exponential moving average over 9 bars |
| `ema_21` | Exponential moving average over 21 bars |
| `ema_50` | Exponential moving average over 50 bars |
| `macd` | MACD line: EMA(12) − EMA(26) |
| `macd_signal` | Signal line: EMA(9) of MACD |
| `atr_14` | Average True Range over 14 bars (volatility gauge) |
| `volume_delta` | Current bar volume minus 20-bar rolling mean (normalized) |
| `bar_range` | High − Low (absolute range of current bar) |
| `close_position` | (Close − Low) / (High − Low) — where close sits in bar's range, 0–1 |

All features use River's rolling stat primitives (`EWMean`, `RollingMean`, `RollingVar`) — they update in O(1) per bar with no stored history.

---

## Incremental Learning Loop

```
New bar closes (NinjaTrader sends OHLCV via TCP)
      │
      ▼
Feature engine — computes all 10 features → feature dict x
      │
      ├──► Model 1  (Scalper)        .predict_one(x) → signal_1
      ├──► Model 2  (Momentum)       .predict_one(x) → signal_2
      ├──► Model 3  (Mean Reversion) .predict_one(x) → signal_3
      ├──► Model 4  (Breakout)       .predict_one(x) → signal_4
      ├──► Model 5  (Conservative)   .predict_one(x) → signal_5
      ├──► Model 6  (Aggressive)     .predict_one(x) → signal_6
      ├──► Model 7  (Volume)         .predict_one(x) → signal_7
      ├──► Model 8  (Contrarian)     .predict_one(x) → signal_8
      ├──► Model 9  (You)            .predict_one(x) → signal_9   (blends 1-8)
      └──► Model 10 (Brother)        .predict_one(x) → signal_10  (blends 1-8)
                │
                ▼
        All 10 signals → WebSocket broadcast to dashboard
                │
                ▼
        Write predictions to TimescaleDB (predictions table)
                │
                ▼
        Next bar closes — actual outcome (y) is now known
        y = 1 if close > prev_close else 0
                │
                ▼
        All 10 models: .learn_one(x, y)
                │
                ▼
        ADWIN drift detectors updated with accuracy reading
                │
                ▼
        Every 100 bars: MLflow snapshot for all models
        (tagged with user_id, model_name, bar_count, accuracy)
```

---

## Per-Model Settings

Every model exposes behavior controls stored in the `model_settings` table (JSONB per user per model):

| Setting | Type | Description |
|---|---|---|
| `signal_mode` | enum | `aggressive` / `balanced` / `conservative` preset that adjusts thresholds |
| `min_confidence` | float 0–1 | Minimum confidence to emit a signal (below this → HOLD) |
| `max_signals_per_session` | int | Cap on BUY/SELL signals per RTH session |
| `learning_enabled` | bool | Pause/resume `.learn_one()` calls for this model |
| `learning_rate` | float | Override model's internal learning rate (where applicable) |
| `drift_detection_enabled` | bool | Enable/disable ADWIN monitoring for this model |
| `model_params` | dict | Model-specific params (see below) |

**Model-specific params examples:**

| Model | Extra params |
|---|---|
| Scalper | `lookback_bars`, `profit_ticks`, `stop_ticks` |
| Conservative | `confidence_floor` (hard minimum above `min_confidence`) |
| Volume | `spike_threshold`, `delta_imbalance_cutoff`, `lookback_window` |
| Aggressive | `target_multiplier` (scales price target width) |
| Personal (9/10) | `blend_overrides` (dict of model → manual weight, null = auto) |

---

## Drift Detection

TradeMeter uses River's **ADWIN** (Adaptive Windowing) drift detector. One detector instance exists per model per user, managed by `drift.py`.

**Trigger condition:** If a model's rolling accuracy drops below `DRIFT_ACCURACY_THRESHOLD` (default 0.60) AND ADWIN confirms a statistically significant change point, the following happens:

1. Model weights are reset to a fresh instance (same class, same hyperparams, zero history)
2. A `drift` event is written to TimescaleDB
3. A WebSocket notification pushes `{"type": "drift", "model": "scalper"}` to the user's dashboard
4. MLflow logs the drift event with the bar count and accuracy at time of reset

Each model's drift detector is fully independent — a drift reset on the Scalper does not affect Momentum or any other model. Personal models (9/10) have their own drift detectors scoped by user_id.

---

## MLflow Model Registry

MLflow runs at `http://localhost:5001`.

Every 100 bars, `snapshot_all()` is called:
- Each model is serialized with `pickle` and logged via `mlflow.log_artifact()`
- Metrics logged: `rolling_accuracy_50`, `total_bars_seen`, `drift_events`
- Tags: `user_id`, `model_name`, `bar_count`
- Registered under run names: `trademeter_{model_name}_{user_id}`

**Rollback:** `mlflow.artifacts.download_artifacts(run_id=...)` retrieves any prior snapshot. The pipeline can hot-swap a model instance without restarting the backend.
