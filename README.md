# TradeMeter

**Live ML-powered trading dashboard for NinjaTrader 8**

![Status](https://img.shields.io/badge/status-in%20development-yellow)
![Stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20React%20%7C%20Redis%20%7C%20TimescaleDB-blue)
![Auth](https://img.shields.io/badge/auth-Google%20OAuth%20%2B%20NT%20Token-green)

---

## What is TradeMeter?

TradeMeter connects your NinjaTrader 8 instance to a live machine learning pipeline and serves real-time predictions directly to a web dashboard. On every new bar, the NinjaTrader strategy sends OHLCV data over TCP to the TradeMeter backend, which processes the tick, updates three incremental River models, and pushes results via WebSocket to your browser.

**Three prediction outputs on every bar:**

| Output | Description |
|---|---|
| **Direction** | Probability the next bar closes higher (0–1) |
| **Price Target** | Predicted price range for the next N bars |
| **Signal** | Discrete action recommendation: BUY / SELL / HOLD |

---

## Architecture

```
NinjaTrader 8
  [LiveDataFeedStrategy.cs]
       |
       | TCP (port 5000)  +  connection token
       v
  TradeMeter Backend (FastAPI)
  [tcp_listener.py]
       |
       v
  Redis Streams  ──────────────────────────────────┐
  [market_data stream]                             |
       |                                           |
       v                                           |
  ML Pipeline (River)                        TimescaleDB
  [direction, target, signal models]         [tick history]
       |
       v
  WebSocket broadcaster
  [/ws/live]
       |
       v
  React Dashboard (Recharts)
  [LiveChart + PredictionPanel + ModelMetrics]
```

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

## Auth Flow

1. User visits TradeMeter and clicks **Sign in with Google**
2. After Google OAuth completes, a JWT cookie is set and a unique NinjaTrader connection token is generated (e.g. `TM-a3f9x2`)
3. User copies the token from the **Connect** page
4. User pastes the token into the `ConnectionToken` parameter of the NinjaTrader strategy
5. Strategy includes the token in every TCP message — backend links the data stream to the user session

---

## Project Structure

| Path | Description |
|---|---|
| `ninja-strategy/` | C# NinjaScript strategy that sends data over TCP |
| `backend/` | FastAPI app — TCP listener, ML pipeline, WebSocket, REST API |
| `frontend/` | React 18 + Vite dashboard |
| `ml/` | Feature definitions and MLflow config |
| `infra/` | Docker Compose + Nginx config |
| `docs/` | Full documentation |

---

## Documentation

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data flow, design decisions |
| [docs/SETUP.md](docs/SETUP.md) | Complete local setup guide |
| [docs/AUTH.md](docs/AUTH.md) | Auth design — Google OAuth + NT token |
| [docs/ML.md](docs/ML.md) | ML pipeline, features, models, drift detection |
| [docs/API.md](docs/API.md) | REST + WebSocket API reference |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Branching, commits, code style |
| [ninja-strategy/README.md](ninja-strategy/README.md) | NinjaTrader install guide |

---

## Tech Stack

| Layer | Technology |
|---|---|
| NinjaTrader strategy | C# / NinjaScript |
| TCP → stream bridge | Python asyncio |
| Message broker | Redis Streams |
| Backend API | FastAPI + uvicorn |
| ML | River (incremental) + MLflow |
| Database | TimescaleDB (PostgreSQL 16) |
| Auth | Google OAuth 2.0 + JWT |
| Frontend | React 18 + Vite + Recharts + Zustand |
| Proxy | Nginx |
| Infra | Docker Compose |

---

## License

MIT © 2026 TradeMeter contributors
