# TradeMeter

**Live ML trading dashboard — 10 incremental models, real-time signals, multi-user**

![Status](https://img.shields.io/badge/status-in%20development-yellow)
![Stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20React%20%7C%20Redis%20%7C%20TimescaleDB%20%7C%20River%20%7C%20MLflow-blue)
![Auth](https://img.shields.io/badge/auth-Google%20OAuth%20%2B%20NT%20Token-green)

---

## What is TradeMeter?

TradeMeter streams live MES futures data from NinjaTrader 8 into a backend that runs **10 parallel incremental ML models** — each with its own trading personality. Every bar close triggers all 10 models simultaneously: they predict direction, price target, and a BUY / SELL / HOLD signal with confidence percentage. All models learn from every bar using River's online learning — no retraining jobs, no batch datasets.

The predictions stream via WebSocket to a React dashboard that shows a live leaderboard ranking models by today's P&L, a grid of 10 model cards updating in real time, and a candlestick chart with signal overlays.

| Model | Personality |
|---|---|
| Scalper | Ultra short-term, high frequency |
| Momentum | Trend follower |
| Mean Reversion | Fades extremes |
| Breakout Hunter | Breakout entries |
| Conservative | Low risk, small moves |
| Aggressive | High risk, big moves |
| Volume | Order flow based |
| Contrarian | Bets against the crowd |
| You (Model 9) | Your personal hybrid — blends best performers |
| Brother (Model 10) | Brother's personal hybrid — same blend logic, separate weights |

**Each user gets their own Google account, NT token, and personal hybrid model. Data is fully isolated per user.**

---

## Architecture

```
NinjaTrader 8 (C# strategy + connection token)
        │  TCP :5000
        ▼
Redis Streams  ──►  FastAPI backend
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
        Feature      10 River    TimescaleDB
        engine       models      (permanent)
              │          │
              └────┬─────┘
                   ▼
             MLflow registry
             (snapshots every 100 bars)
                   │
             WebSocket feed
                   │
          React dashboard
          (10 model cards + leaderboard)
```

---

## Auth Flow

1. User visits TradeMeter and clicks **Sign in with Google**
2. After OAuth completes, the Connect page shows a unique NinjaTrader token (e.g. `TM-a3f9x2`)
3. User pastes the token into the `ConnectionToken` parameter in their NinjaTrader strategy
4. Strategy sends the token with every TCP message — backend links the data stream to the user, connection status turns green

---

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/AbdelrahmanYousef9266/TradeMeter.git
cd TradeMeter
cp .env.example .env
# Fill in GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET

# 2. Start infrastructure
docker compose -f infra/docker/docker-compose.yml up -d

# 3. Run backend
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 4. Run frontend
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| NinjaTrader strategy | C# / NinjaScript (.NET 4.8) |
| Message broker | Redis Streams |
| Backend API | FastAPI + uvicorn (Python 3.11) |
| ML | River (incremental) — Hoeffding Tree, Logistic Regression, Naive Bayes |
| Model registry | MLflow |
| Database | TimescaleDB (PostgreSQL 16) |
| Auth | Google OAuth 2.0 + JWT + NT connection token |
| Frontend | React 18 + Vite + Recharts + Zustand |
| Proxy | Nginx |
| Infra | Docker Compose |

---

## Multi-User

TradeMeter is designed for multiple independent users. Each user:
- Logs in with their own Google account
- Gets a unique NinjaTrader connection token
- Has fully isolated tick history, prediction history, and model weights
- Gets their own personal hybrid model that blends the best-performing models for them

Two users (or more) can connect from separate machines simultaneously with no data crossover.

---

## Documentation

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data flow, design decisions |
| [docs/SETUP.md](docs/SETUP.md) | Complete local setup guide |
| [docs/AUTH.md](docs/AUTH.md) | Two-step auth — Google OAuth + NT token |
| [docs/ML.md](docs/ML.md) | 10 models, features, incremental learning, drift detection |
| [docs/API.md](docs/API.md) | REST + WebSocket API reference |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Branching, commits, code style, adding new models |
| [ninja-strategy/README.md](ninja-strategy/README.md) | NinjaTrader install guide |

---

## License

MIT © 2026 TradeMeter contributors
