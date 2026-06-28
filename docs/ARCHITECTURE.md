# Architecture

## Overview

TradeMeter runs **10 parallel incremental ML models** on live NinjaTrader data. Each model has its own trading personality, independent weights, and tunable behavior settings. All models update using River's `.learn_one()` on every bar close — no retraining, no batch jobs, no stored datasets. The backend is a single FastAPI process running multiple async tasks: a TCP listener, a Redis Streams consumer, a 10-model ML inference loop, and a WebSocket broadcaster. Every row in every database table is scoped by `user_id` — multiple users can connect from separate machines with complete data isolation.

---

## Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  NinjaTrader 8 (user's machine)                                              │
│  LiveDataFeedStrategy.cs                                                     │
│  On each bar close: TOKEN|TIMESTAMP|SYMBOL|OPEN|HIGH|LOW|CLOSE|VOLUME|TYPE\n │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │  TCP :5000 (newline-delimited pipe-separated)
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  tcp_listener.py  (asyncio TCP server)                                       │
│  • Validates token → SHA-256 hash lookup → resolves to user_id              │
│  • Caches tcp_conn → user_id in Redis                                        │
│  • Publishes to Redis Stream key: market:raw                                 │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │  XADD market:raw
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Redis Streams                                                               │
│  Stream: market:raw — volatile tick buffer, crash-safe consumer group       │
└──────────┬────────────────────────────────────────────────────────────────────┘
           │  XREADGROUP (blocking, consumer group: ingestion)
           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  ingestion.py  (Redis consumer task)                                         │
│  • Writes tick to TimescaleDB (ticks hypertable)                            │
│  • Calls features.py → 10 features computed from raw OHLCV                  │
│  • Passes feature vector + user_id to ML pipeline                           │
└───────────┬──────────────────────────────────────────────────────────────────┘
            │
            ├──────────────────────────┐
            ▼                          ▼
┌─────────────────────┐   ┌──────────────────────────────────────────────────┐
│  TimescaleDB        │   │  ML Pipeline — 10 parallel models               │
│  ticks hypertable   │   │                                                  │
│  (permanent)        │   │  predict_all(features, user_id):                │
└─────────────────────┘   │  ├─ Model 1: Scalper        .predict_one()      │
                          │  ├─ Model 2: Momentum       .predict_one()      │
                          │  ├─ Model 3: Mean Reversion .predict_one()      │
                          │  ├─ Model 4: Breakout       .predict_one()      │
                          │  ├─ Model 5: Conservative   .predict_one()      │
                          │  ├─ Model 6: Aggressive     .predict_one()      │
                          │  ├─ Model 7: Volume         .predict_one()      │
                          │  ├─ Model 8: Contrarian     .predict_one()      │
                          │  ├─ Model 9: You (personal) .predict_one()      │
                          │  └─ Model 10: Brother       .predict_one()      │
                          │                    │                             │
                          │             all 10 signals                      │
                          └──────────────────┬───────────────────────────────┘
                                             │
                                             ▼
                          ┌──────────────────────────────────────────────────┐
                          │  WebSocket broadcaster  /market/live             │
                          │  Pushes bar + all 10 model signals to user's     │
                          │  connected browser clients                       │
                          └───────────────────────┬──────────────────────────┘
                                                  │
                                                  ▼
                          ┌──────────────────────────────────────────────────┐
                          │  React Dashboard                                 │
                          │  Leaderboard → 10 model cards → LiveChart       │
                          └──────────────────────────────────────────────────┘

                  ◄── Feedback loop ──────────────────────────────────────────►

  Next bar close → actual outcome (label) known
       │
       ▼
  learn_all(features, label, user_id):
  All 10 models call .learn_one(features, label)
       │
       ▼
  Every 100 bars: MLflow.log_model() snapshot for all models
  (tagged with user_id, model_name, bar_count, rolling_accuracy)
```

---

## Folder Structure

```
TradeMeter/
├── .github/                        CI workflows and issue templates
├── ninja-strategy/
│   ├── LiveDataFeedStrategy.cs     C# NinjaScript — TCP publisher
│   └── README.md                   NinjaTrader install guide
├── backend/
│   ├── app/
│   │   ├── main.py                 FastAPI entry point + startup tasks
│   │   ├── core/
│   │   │   ├── config.py           Pydantic-settings env loader
│   │   │   ├── security.py         JWT, token gen, bcrypt, OAuth verify
│   │   │   └── redis.py            Redis Streams client + prediction cache
│   │   ├── api/routes/
│   │   │   ├── auth.py             Google OAuth + NT token endpoints
│   │   │   ├── market.py           OHLCV history + WebSocket /market/live
│   │   │   ├── predictions.py      Latest + history predictions
│   │   │   ├── models.py           10-model management + leaderboard  ← NEW
│   │   │   └── settings.py         Global user settings
│   │   ├── models/
│   │   │   ├── user.py             SQLAlchemy User table
│   │   │   ├── tick.py             SQLAlchemy Tick hypertable
│   │   │   ├── prediction.py       SQLAlchemy Prediction table
│   │   │   └── model_settings.py   SQLAlchemy ModelSettings table  ← NEW
│   │   ├── services/
│   │   │   ├── market_data/
│   │   │   │   ├── tcp_listener.py Asyncio TCP server, token validation
│   │   │   │   ├── ingestion.py    Redis consumer, DB writes
│   │   │   │   └── features.py     10-feature computation engine
│   │   │   └── ml/
│   │   │       ├── pipeline.py     MODEL_REGISTRY + predict/learn orchestration
│   │   │       ├── ensemble.py     Personal model blend logic  ← NEW
│   │   │       ├── drift.py        ADWIN drift detector wrapper  ← NEW
│   │   │       └── models/         One file per personality  ← NEW DIR
│   │   │           ├── scalper.py
│   │   │           ├── momentum.py
│   │   │           ├── mean_reversion.py
│   │   │           ├── breakout.py
│   │   │           ├── conservative.py
│   │   │           ├── aggressive.py
│   │   │           ├── volume.py
│   │   │           ├── contrarian.py
│   │   │           └── personal.py
│   │   └── db/
│   │       ├── database.py         asyncpg pool + create_hypertable
│   │       └── migrations/001_initial.sql
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── Login.jsx
│       │   ├── Connect.jsx
│       │   ├── Dashboard.jsx
│       │   ├── Settings.jsx
│       │   └── ModelSettings.jsx   Per-model tuning page  ← NEW
│       ├── components/
│       │   ├── chart/              LiveChart, VolumeBar
│       │   ├── dashboard/
│       │   │   ├── ModelCard.jsx   Single model card  ← REPLACES PredictionPanel
│       │   │   └── Leaderboard.jsx Top bar ranking  ← REPLACES ModelMetrics
│       │   ├── settings/
│       │   │   ├── StrategyConfig.jsx
│       │   │   ├── IndicatorToggles.jsx
│       │   │   └── ModelBehavior.jsx  Reusable behavior form  ← NEW
│       │   └── auth/
│       ├── hooks/                  useWebSocket, usePredictions
│       ├── store/index.js          Zustand global state
│       └── services/api.js         Axios client
├── ml/
│   ├── features/definitions.py
│   └── registry/mlflow_config.py
├── infra/
│   ├── docker/docker-compose.yml
│   └── nginx/nginx.conf
└── docs/
```

---

## Key Design Decisions

### Why 10 parallel models instead of one?

Each personality captures a different market regime. A single model trained on everything will average out the regimes and perform mediocrely in all of them. Running 10 independent models lets the leaderboard surface which personality the current market is rewarding, and the personal hybrid model (9/10) dynamically shifts weight toward the current winner without losing the other perspectives.

### Why River for incremental learning?

River is the only mature Python library for true online learning — models update with a single `.learn_one()` call per bar, requiring no stored dataset. Scikit-learn would require keeping a growing historical buffer and scheduling periodic refits. For a live trading system that must adapt continuously, River's design is the only correct choice.

### Why independent weights per model?

If all 10 models shared weights, their personalities would average out. The Contrarian model would partially absorb Momentum's gradient on every bar and lose its distinctive behavior. Independent weights mean personalities are preserved — the Scalper stays a Scalper even in trending markets; it just appears lower on the leaderboard until the regime rotates.

### Why personal models blend the top performers dynamically?

Blend weights are recomputed every bar from the rolling 50-bar accuracy of models 1-8. This means the personal model automatically shifts toward whoever is currently winning — when Momentum is hot, the personal model becomes more momentum-like. Users can also pin manual overrides to lock a blend they trust regardless of recent accuracy.

### Why Redis Streams?

Redis Streams provide a durable, ordered, consumer-group-aware message log. The TCP listener publishes at potentially high frequency; the ingestion worker can lag without losing messages because they accumulate in the stream. XACK semantics guarantee no bar is skipped even if the backend restarts mid-session. An in-process `asyncio.Queue` would lose buffered messages on crash.

### Why TimescaleDB?

Tick data is purely append-only with heavy range-query access patterns ("last 500 bars for user X"). TimescaleDB hypertables partition the ticks table by time automatically, delivering ~10× faster range queries than vanilla Postgres and native time-series compression. The `predictions` table also benefits from the same time-indexed query patterns.

### Why MLflow?

Snapshots every 100 bars let us roll back any single model independently if a personality drifts badly. MLflow tags each snapshot with `user_id`, `model_name`, `bar_count`, and `rolling_accuracy`, making it possible to restore a specific user's specific model to a specific known-good state without affecting any other model or user.

### Why the connection token auth pattern?

NinjaTrader 8 is a local desktop application running on .NET 4.8 with no ability to participate in a browser OAuth flow. The connection token is a short-lived, user-scoped secret that bridges the TCP connection to the authenticated browser session. The token is stored bcrypt-hashed in the database — even if the database is compromised, raw tokens are never exposed.

### Multi-user data isolation

Every row in `ticks`, `predictions`, and `model_settings` carries a `user_id` UUID foreign key. All queries are `WHERE user_id = $1`. Personal models 9 and 10 are instances of the same `personal.py` class, differentiated only by the `user_id` they are initialized with. Adding a third user creates Model 11 automatically with the same mechanism.
