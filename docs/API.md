# API Reference

## Base URL

```
http://localhost:8000
```

All REST endpoints are prefixed with `/api/v1` except auth endpoints which are at root.

---

## Auth Requirement

Endpoints marked **JWT** require the session cookie set by Google OAuth. Endpoints return `401 Unauthorized` if the cookie is missing or expired.

---

## Auth Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/google` | None | Redirect to Google OAuth consent screen |
| `GET` | `/auth/google/callback` | None | Handle callback, create user, set JWT cookie |
| `POST` | `/auth/logout` | JWT | Clear session cookie |
| `GET` | `/auth/me` | JWT | Return current user from JWT |
| `GET` | `/auth/nt-token` | JWT | Return user's NT connection token |
| `GET` | `/auth/nt-status` | JWT | Return `{ "connected": bool, "last_seen": timestamp }` |
| `POST` | `/auth/rotate-token` | JWT | Generate new NT token, drop active TCP connection |

---

## Market Data Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/market/history` | JWT | Return OHLCV bars for the authenticated user |
| `WS` | `/market/live` | JWT cookie | WebSocket — streams bar + all 10 model signals on each bar close |

**GET /api/v1/market/history query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 100 | Number of bars to return |
| `from_ts` | int | — | Unix timestamp lower bound |
| `to_ts` | int | — | Unix timestamp upper bound |
| `symbol` | string | — | Filter by instrument symbol |

---

## WebSocket Message Format

Connect to `ws://localhost:8000/market/live` with the JWT cookie present. One message per bar close:

```json
{
  "time": "2025-03-15T14:32:00Z",
  "bar": {
    "open": 5841.25,
    "high": 5844.0,
    "low": 5840.5,
    "close": 5843.0,
    "volume": 980
  },
  "models": {
    "scalper": {
      "signal": "BUY",
      "confidence": 0.70,
      "direction": { "up": 0.70, "down": 0.30 },
      "target": { "high": 5846.0, "low": 5840.0 }
    },
    "momentum": {
      "signal": "BUY",
      "confidence": 0.87,
      "direction": { "up": 0.87, "down": 0.13 },
      "target": { "high": 5848.0, "low": 5836.0 }
    },
    "mean_rev": {
      "signal": "SELL",
      "confidence": 0.72,
      "direction": { "up": 0.28, "down": 0.72 },
      "target": { "high": 5845.0, "low": 5835.0 }
    },
    "breakout": {
      "signal": "BUY",
      "confidence": 0.79,
      "direction": { "up": 0.79, "down": 0.21 },
      "target": { "high": 5855.0, "low": 5838.0 }
    },
    "conservative": {
      "signal": "HOLD",
      "confidence": 0.83,
      "direction": { "up": 0.52, "down": 0.48 },
      "target": { "high": 5843.0, "low": 5838.5 }
    },
    "aggressive": {
      "signal": "SELL",
      "confidence": 0.65,
      "direction": { "up": 0.35, "down": 0.65 },
      "target": { "high": 5848.0, "low": 5830.0 }
    },
    "volume": {
      "signal": "BUY",
      "confidence": 0.70,
      "direction": { "up": 0.70, "down": 0.30 },
      "target": { "high": 5846.0, "low": 5837.0 }
    },
    "contrarian": {
      "signal": "SELL",
      "confidence": 0.58,
      "direction": { "up": 0.42, "down": 0.58 },
      "target": { "high": 5847.0, "low": 5833.0 }
    },
    "you": {
      "signal": "BUY",
      "confidence": 0.81,
      "direction": { "up": 0.81, "down": 0.19 },
      "target": { "high": 5846.0, "low": 5840.0 },
      "blend": { "momentum": 0.40, "breakout": 0.35, "personal": 0.25 }
    },
    "brother": {
      "signal": "BUY",
      "confidence": 0.76,
      "direction": { "up": 0.76, "down": 0.24 },
      "target": { "high": 5847.0, "low": 5839.0 },
      "blend": { "momentum": 0.30, "scalper": 0.40, "personal": 0.30 }
    }
  }
}
```

Drift events are pushed as separate messages:

```json
{
  "type": "drift",
  "model": "scalper",
  "time": "2025-03-15T14:35:00Z",
  "accuracy_at_reset": 0.54
}
```

---

## Models Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/models` | JWT | List all 10 models with current status and today's P&L |
| `GET` | `/api/v1/models/leaderboard` | JWT | All models ranked by today's P&L |
| `GET` | `/api/v1/models/{model_id}` | JWT | Single model detail: accuracy, current signal, settings |
| `GET` | `/api/v1/models/{model_id}/settings` | JWT | Get model's current behavior settings |
| `PUT` | `/api/v1/models/{model_id}/settings` | JWT | Update model behavior settings |
| `POST` | `/api/v1/models/{model_id}/reset` | JWT | Reset model weights to defaults |
| `GET` | `/api/v1/models/{model_id}/history` | JWT | Model accuracy history over time |

**PUT /api/v1/models/{model_id}/settings request body example:**

```json
{
  "signal_mode": "balanced",
  "min_confidence": 0.65,
  "max_signals_per_session": 10,
  "learning_enabled": true,
  "learning_rate": 0.01,
  "drift_detection_enabled": true,
  "model_params": {
    "spike_threshold": 1.5,
    "delta_imbalance_cutoff": 0.6
  }
}
```

---

## Predictions Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/predictions/latest` | JWT | Most recent signal from all 10 models |
| `GET` | `/api/v1/predictions/history` | JWT | Past predictions with actual outcomes |

---

## Settings Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/settings` | JWT | User's global settings: instrument, bar type, active indicators |
| `PUT` | `/api/v1/settings` | JWT | Update global settings |

**PUT /api/v1/settings request body:**

```json
{
  "instrument": "MES SEP24",
  "bar_type": "1MIN",
  "active_indicators": ["rsi_14", "ema_9", "ema_21", "macd", "atr_14"]
}
```
