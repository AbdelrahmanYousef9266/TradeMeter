# API Reference

## Base URL

```
http://localhost:8000
```

All REST endpoints are prefixed with `/api/v1`.

---

## Auth Requirement

Most endpoints require a valid JWT session cookie set by the Google OAuth flow. Endpoints that require auth return `401 Unauthorized` if the cookie is missing or expired.

The WebSocket endpoint additionally requires the user to have an active NinjaTrader connection.

---

## Auth Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/google` | None | Redirect to Google OAuth consent screen |
| `GET` | `/auth/google/callback` | None | Handle OAuth callback, set JWT cookie |
| `GET` | `/auth/me` | JWT | Return current user info |
| `POST` | `/auth/logout` | JWT | Clear session cookie |

---

## Market Data Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/market/history` | JWT | Return recent bars for the authenticated user |
| `GET` | `/api/v1/market/status` | JWT | Return TCP connection status (connected / disconnected) |

**GET /api/v1/market/history query params:**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 100 | Number of bars to return |
| `from_ts` | int | — | Unix timestamp lower bound |
| `to_ts` | int | — | Unix timestamp upper bound |

---

## WebSocket

**Endpoint:** `ws://localhost:8000/ws/live`

Connect with the JWT cookie present. The server pushes one message per bar:

```json
{
  "type": "bar",
  "ts": 1719400000,
  "bar": {
    "open": 5100.25,
    "high": 5101.50,
    "low": 5099.75,
    "close": 5100.75,
    "volume": 342
  },
  "prediction": {
    "direction": {
      "up": 0.72,
      "down": 0.28
    },
    "target": {
      "low": 5099.0,
      "high": 5103.5
    },
    "signal": "BUY"
  },
  "model_metrics": {
    "direction_accuracy": 0.634,
    "target_mae": 1.25,
    "bar_count": 847
  }
}
```

Drift events are pushed as separate messages:

```json
{
  "type": "drift",
  "model": "direction",
  "ts": 1719400120
}
```

---

## Predictions Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/predictions/latest` | JWT | Return the most recent prediction for the user |
| `GET` | `/api/v1/predictions/history` | JWT | Return prediction history with actuals |
| `GET` | `/api/v1/predictions/metrics` | JWT | Return current model accuracy metrics |

---

## Settings Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/settings` | JWT | Return user settings |
| `PUT` | `/api/v1/settings` | JWT | Update user settings |
| `POST` | `/api/v1/settings/rotate-token` | JWT | Generate a new NT connection token |

**PUT /api/v1/settings request body:**

```json
{
  "signal_threshold": 0.65,
  "enabled_indicators": ["rsi_14", "ema_diff", "vol_z"],
  "alert_on_signal": true,
  "alert_on_drift": true
}
```
