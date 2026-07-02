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

Sixteen features are computed from raw OHLCV data by `features.py` before being passed to any model:

| Feature | Description |
|---|---|
| `rsi_14` | RSI(14) using Wilder's smoothing |
| `ema_9` | Exponential moving average over 9 bars |
| `ema_21` | Exponential moving average over 21 bars |
| `ema_50` | Exponential moving average over 50 bars |
| `macd` | MACD line: EMA(12) − EMA(26) |
| `macd_signal` | Signal line: EMA(9) of MACD |
| `atr_14` | Average True Range over 14 bars (volatility gauge) |
| `volume_delta` | Current bar volume vs 20-bar rolling mean (normalized) |
| `bar_range` | High − Low (absolute range of current bar) |
| `close_position` | (Close − Low) / (High − Low) — where close sits in bar's range, 0–1 |
| `vwap` | Session VWAP price (resets 9:30 AM ET daily, typical price weighted) |
| `vwap_distance` | (close − vwap) / vwap — how far price is from fair value |
| `vwap_cross` | 1.0 = crossed above VWAP this bar, −1.0 = crossed below, 0.0 = no cross |
| `session_minutes` | Minutes elapsed since 9:30 AM ET open (0 = open, 390 = close) |
| `session_phase` | Normalized session position 0.0 (open) to 1.0 (close) |
| `is_power_hour` | 1.0 if current bar is between 3:00–4:00 PM ET, else 0.0 |

All features update in O(1) per bar with no stored history beyond a 20-bar volume window.

---

## Incremental Learning Loop

```
New bar closes (NinjaTrader sends OHLCV via TCP)
      │
      ▼
Feature engine — computes all 16 features → feature dict x
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

---

## Model Level System

Every model instance earns XP as it learns from live bars. XP accumulates toward levels (1–100) that unlock settings and increase blend weight in the personal models. XP and level are tracked **per model per user** — each user's copy of the 8 shared models levels up independently based on that user's own data stream.

### XP Sources (awarded per bar, per model)

| Event | XP |
|-------|----|
| Bar learned from (every bar) | +1 XP |
| Correct direction prediction | +10 XP |
| P&L improvement on that bar | +5 XP |
| Consecutive correct signal (× current streak count) | +3 XP |
| Wrong prediction | −3 XP |

**XP floor:** XP never goes below 0. A Rookie model cannot accumulate negative XP.

**Streak bonus:** The streak counter increments by 1 for each consecutive correct signal. A single wrong prediction resets the streak to 0. A 5-streak bar earns +15 XP from the streak bonus alone.

### Rank Tiers

| Level | Rank | Color |
|-------|------|-------|
| 1–19 | Rookie | Gray |
| 20–39 | Apprentice | Blue |
| 40–59 | Pro | Teal |
| 60–79 | Elite | Purple |
| 80–99 | Expert | Amber |
| 100 | Master | Coral |

### XP to Next Level Formula

| Level range | XP required per level |
|-------------|-----------------------|
| 1–20 | 300 XP |
| 21–50 | 500 XP |
| 51–80 | 800 XP |
| 81–99 | 1 200 XP |
| 100 | Final tier — no next level |

### Unlock Progression

| Rank reached | What unlocks |
|-------------|-------------|
| Apprentice (Lv 20) | Confidence threshold slider |
| Pro (Lv 40) | Signal mode presets (Aggressive / Balanced / Conservative) |
| Elite (Lv 60) | Blend weight visible and adjustable in personal models |
| Expert (Lv 80) | Aggressive settings (wide targets, low confidence floor) |
| Master (Lv 100) | All settings fully unlocked · max blend weight |

### Effect on Personal Model Blend Weight

When models 1–8 contribute to the personal hybrid (models 9 and 10), their base blend weight is their rolling 50-bar accuracy (normalized). Rank multipliers are applied on top:

| Rank | Blend weight multiplier |
|------|------------------------|
| Rookie / Apprentice / Pro | 1.0× (base accuracy) |
| Elite (Lv 60+) | 1.5× |
| Master (Lv 100) | 2.0× |

After multipliers are applied, weights are renormalized to sum to 1.0. A Master-ranked Momentum model will dominate the personal blend if it is also accurate. User manual overrides clamp and renormalize after the rank multipliers.

### Dashboard Notifications

When a model levels up, `pipeline.py` publishes a `level_up` event to the Redis pub/sub channel `live:{user_id}`. The WebSocket broadcaster forwards it to the browser, where a toast notification plays a level-up animation on the relevant model card.

---

## Model 11 — Deep LSTM

Model 11 is fundamentally different from models 1–10. It is a **PyTorch LSTM** that learns multi-bar **sequence** patterns the per-bar River models cannot capture.

| Aspect | River models (1–10) | LSTM (Model 11) |
|--------|---------------------|-----------------|
| Learning | Online — `learn_one()` every bar | Batch — trained on full history |
| When it learns | Continuously, live | Nightly (2 AM ET) + manual button |
| Input | Single bar's 16 features | **50-bar sequence** of 16 features |
| Prediction | Every bar, always | Live inference, **only when trained** |
| Persistence | Pickled River objects | Pickled `state_dict` + normalization stats |

### Architecture

- `nn.LSTM` with 2 layers, hidden size 64, dropout 0.2, over `(batch, 50, 16)` sequences.
- A small head (`Linear 64→32 → ReLU → Dropout → Linear 32→3`) classifies the final timestep into **SELL / HOLD / BUY**.
- Inputs are normalized using the per-feature mean/std computed at training time (stored alongside the weights).

### Training

- **Data**: all of the user's bar closes from TimescaleDB (`ticks`), with features recomputed in chronological order using the same `FeatureEngine` as live.
- **Labels**: for a sequence ending at bar *t*, look at the next bar — BUY if `close[t+1] − close[t] > 0.5·ATR`, SELL if `< −0.5·ATR`, else HOLD.
- **Imbalance**: class-weighted `CrossEntropyLoss` (HOLD is usually most common).
- **Split**: chronological 80/20 train/validation; validation accuracy is reported back to the dashboard.
- Trained weights are saved to the shared `model_state` table under `model_name = 'lstm'` and reloaded into the live pipeline immediately.

### Dormancy

The LSTM stays **dormant** until **2000 bars** of history exist. While dormant it:
- Makes **no predictions** (returns HOLD with confidence 0), so it opens no trades.
- Still feeds its rolling 50-bar window every bar, so the moment it is trained it has a full window ready for inference.
- Shows "🧬 Collecting data — X / 2000 bars" with a progress bar on its dashboard card.

### Triggers

1. **Nightly** — a background task in `main.py` retrains every active user's LSTM around 2 AM ET.
2. **Manual** — `POST /models/lstm/train` (the "Train now / Retrain" button). Status comes from `GET /models/lstm/status`.

### Leaderboard & XP

Model 11 opens simulated trades and competes on **P&L** like every other model, and earns **XP** from winning trades. It does **not** use Champion/Challenger (there are no per-bar hyperparameters to mutate — it is batch-trained), and it has no online weights to reset (`reset` and `settings` endpoints return 400 for `lstm`; use `train` instead).

> Note: torch runs on **CPU** — no GPU is required at this scale. See `docs/SETUP.md`.
