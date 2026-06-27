# Architecture

## Overview

TradeMeter is a pipeline system with four distinct layers: data ingestion (NinjaTrader → TCP), stream processing (Redis Streams), ML inference (River models), and presentation (WebSocket → React). Each layer is decoupled so any component can be replaced or scaled independently. The backend is a single FastAPI process running several async tasks concurrently: the TCP listener, the Redis consumer, the ML inference loop, and the WebSocket broadcaster.

---

## Data Flow

```
┌────────────────────────────────────────────────────────────────────┐
│  NinjaTrader 8 (user's machine)                                    │
│  LiveDataFeedStrategy.cs                                           │
│  On each new bar: serialize OHLCV + token → send to TCP port 5000  │
└───────────────────────┬────────────────────────────────────────────┘
                        │ TCP socket (JSON line per bar)
                        │ { "token": "TM-a3f9x2", "open": 5100.25, ... }
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│  tcp_listener.py  (asyncio TCP server)                             │
│  • Validates connection token → resolves to user_id               │
│  • Publishes raw bar to Redis Stream "market_data"                 │
└───────────────────────┬────────────────────────────────────────────┘
                        │ XADD market_data * user_id=... open=... ...
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│  Redis Streams  (in-memory message broker)                         │
│  Stream key: market_data                                           │
│  Consumer group: ml_pipeline                                       │
└───────────────────────┬────────────────────────────────────────────┘
                        │ XREADGROUP (blocking read)
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│  ingestion.py  (Redis consumer)                                    │
│  • Reads from stream                                               │
│  • Calls features.py → computes 10 engineered features            │
│  • Persists raw tick to TimescaleDB                                │
│  • Passes feature vector to ML pipeline                            │
└──────────┬─────────────────────────────────┬───────────────────────┘
           │                                 │
           ▼                                 ▼
┌─────────────────────┐          ┌───────────────────────────────────┐
│  TimescaleDB        │          │  ML Pipeline (River)               │
│  tick history       │          │  • direction model (Hoeffding Tree)│
│  hypertable on ts   │          │  • target model (SNARIMAX)         │
└─────────────────────┘          │  • signal model (Logistic + rules) │
                                 │  • learn_one() on every bar        │
                                 │  • predict_one() → prediction dict │
                                 │  • MLflow: log metrics + snapshots │
                                 └─────────────────┬─────────────────┘
                                                   │
                                                   ▼
                                 ┌─────────────────────────────────────┐
                                 │  WebSocket broadcaster               │
                                 │  Pushes combined tick + prediction   │
                                 │  to all subscribed WS clients        │
                                 │  for the matching user_id            │
                                 └─────────────────┬───────────────────┘
                                                   │ ws://localhost:8000/ws/live
                                                   ▼
                                 ┌─────────────────────────────────────┐
                                 │  React Dashboard                    │
                                 │  useWebSocket hook → Zustand store  │
                                 │  LiveChart (Recharts)               │
                                 │  PredictionPanel + ModelMetrics     │
                                 └─────────────────────────────────────┘
```

---

## Folder Structure

```
TradeMeter/
├── .github/                   CI workflows and issue templates
├── ninja-strategy/            C# NinjaScript — runs inside NinjaTrader
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI entry point
│   │   ├── core/              Config, security helpers, Redis client
│   │   ├── api/routes/        REST endpoints (auth, market, predictions, settings)
│   │   ├── models/            Pydantic + DB schemas
│   │   ├── services/
│   │   │   ├── market_data/   TCP listener, Redis ingestion, feature engineering
│   │   │   └── ml/            River model wrappers and signal logic
│   │   └── db/                Async DB client and SQL migrations
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/             Login, Connect, Dashboard, Settings
│       ├── components/        Chart, dashboard panels, auth UI
│       ├── hooks/             useWebSocket, usePredictions
│       ├── store/             Zustand global state
│       └── services/          Axios API client
├── ml/
│   ├── features/              Shared feature definitions
│   └── registry/              MLflow configuration
├── infra/
│   ├── docker/                docker-compose.yml
│   └── nginx/                 Reverse proxy config
└── docs/                      Architecture, setup, auth, ML, API, contributing
```

---

## Key Design Decisions

### Why Redis Streams?

Redis Streams provide a persistent, ordered, consumer-group-aware message log. The TCP listener publishes at high frequency; the ML consumer can lag without data loss because messages accumulate in the stream. XACK semantics mean no bar is dropped even if the ML pipeline restarts. An in-process queue (asyncio.Queue) was considered but offers no persistence across restarts.

### Why River for ML?

River is the only mature Python library for truly incremental (online) learning — models update with a single call to `learn_one()` on every bar without storing any history. This matches the trading use case exactly: the model improves continuously with live data rather than requiring periodic batch retraining. Scikit-learn would require storing a growing dataset and a scheduled refit job.

### Why TimescaleDB?

Tick data is append-only time-series with high write throughput and range-query access patterns (e.g. "last 500 bars for this user"). TimescaleDB's hypertables partition by time automatically, give ~10× faster range queries than vanilla Postgres, and support continuous aggregates for OHLCV rollups. Plain Postgres was considered but would need manual partitioning and lacks native time-series compression.

### Why the Connection Token pattern?

Users run NinjaTrader on a local machine that has no web session. Google OAuth alone cannot authenticate a TCP connection originating from a desktop application. The connection token is a short-lived, user-scoped secret that the NinjaTrader strategy includes in every message. The backend validates the token on the first message per connection and caches the resolved `user_id` for the lifetime of that TCP session. This avoids embedding OAuth credentials inside the NinjaScript code and lets users rotate tokens without reinstalling the strategy.
