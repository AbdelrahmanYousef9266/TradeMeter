# ML Pipeline

## Overview

TradeMeter uses **incremental (online) machine learning** via the River library. Unlike batch ML where you train once on historical data and periodically retrain, River models update their internal state on every single data point using `learn_one()`. This means the models are always adapting to current market conditions without any retraining jobs, growing datasets, or scheduled refreshes.

The ML pipeline runs as an async task inside the FastAPI process, consuming bars from Redis Streams as they arrive.

---

## Three Models

| Model | Algorithm | Input | Output |
|---|---|---|---|
| **Direction** | Hoeffding Tree Classifier | 10 feature vector | `{"up": 0.72, "down": 0.28}` — probability of next close > current close |
| **Price Target** | SNARIMAX (River time series) | Close price history | `{"low": 5099.0, "high": 5103.5}` — predicted range for next N bars |
| **Signal** | Logistic Regression + rule overlay | Direction prob + features | `"BUY"` / `"SELL"` / `"HOLD"` |

All three models update (`learn_one`) and predict (`predict_one`) on every bar in sequence.

---

## Features

Ten features are computed from raw OHLCV data before being passed to the models:

| Feature | Description |
|---|---|
| `returns_1` | Close-to-close return: `(close - prev_close) / prev_close` |
| `returns_5` | 5-bar rolling return |
| `hl_range` | High-low range normalized by close: `(high - low) / close` |
| `body_ratio` | Candle body as fraction of range: `abs(close - open) / (high - low)` |
| `upper_wick` | Upper wick fraction: `(high - max(open, close)) / (high - low)` |
| `lower_wick` | Lower wick fraction: `(min(open, close) - low) / (high - low)` |
| `vol_z` | Volume z-score over rolling 20-bar window |
| `rsi_14` | RSI(14) computed incrementally |
| `ema_diff` | (EMA9 - EMA21) / close — momentum signal |
| `bar_of_session` | Bar index within current RTH session (captures time-of-day pattern) |

---

## Incremental Learning Loop

```
New bar arrives from Redis Stream
         │
         ▼
  features.py: compute feature vector x
         │
         ▼
  direction_model.predict_one(x)  → direction_proba
  target_model.predict_one(x)     → price_range
  signal_model.predict_one(x)     → signal
         │
         ▼
  Broadcast prediction to WebSocket clients
         │
         ▼
  Wait for next bar's actual outcome (y = did_price_go_up)
         │
         ▼
  direction_model.learn_one(x, y)
  target_model.learn_one(x, actual_close)
  signal_model.learn_one(x, y)
         │
         ▼
  Log metrics to MLflow
  (accuracy, MAE, bar_count)
         │
         └── every MODEL_SNAPSHOT_INTERVAL bars:
             save model snapshot to MLflow registry
```

The key insight: prediction happens first (before the outcome is known), then learning happens on the next bar when the outcome is available. This mirrors real trading — you act on a prediction, then observe what actually happened.

---

## MLflow Model Registry

MLflow runs as a Docker service at `http://localhost:5001`.

**What is logged on every bar:**
- `direction_accuracy` — rolling accuracy of the direction model
- `target_mae` — mean absolute error of price target predictions
- `bar_count` — total bars processed per user

**Snapshots** are taken every `MODEL_SNAPSHOT_INTERVAL` bars (default: 100) and registered in MLflow under the model name `trademeter_direction`, `trademeter_target`, `trademeter_signal`. This allows rollback to a prior checkpoint if drift correction overshoots.

---

## Drift Detection

TradeMeter uses River's **ADWIN** (Adaptive Windowing) drift detector on the direction model's accuracy stream.

| Parameter | Default | Description |
|---|---|---|
| `DRIFT_ACCURACY_THRESHOLD` | `0.60` | If rolling accuracy drops below this, drift is flagged |
| ADWIN delta | `0.002` | Sensitivity of the statistical change detector |

**When drift is detected:**
1. The affected model is reset to a fresh instance (weights cleared)
2. A drift event is logged to MLflow with the bar timestamp and user_id
3. A WebSocket notification is pushed to the dashboard: `{"type": "drift", "model": "direction"}`
4. The model begins re-learning from scratch on live data

Resetting rather than rolling back is intentional: if drift is detected, it means the old model's weights are no longer valid for the current regime. A fresh model adapts faster than one loaded from a stale snapshot.
