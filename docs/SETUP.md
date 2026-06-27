# Local Setup Guide

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | Use pyenv or official installer |
| Node.js | 20 LTS | Use nvm or official installer |
| Docker Desktop | Latest | Runs Redis, TimescaleDB, MLflow |
| Git | Any | |
| NinjaTrader 8 | Latest | With a working MES data feed |
| Google Cloud account | — | For OAuth credentials |

---

## Step 1 — Clone and Configure

```bash
git clone https://github.com/AbdelrahmanYousef9266/TradeMeter.git
cd TradeMeter
cp .env.example .env
```

Open `.env` and fill in:

**Google OAuth credentials** — get these from [Google Cloud Console](https://console.cloud.google.com):
1. Create a project → APIs & Services → Credentials → Create OAuth 2.0 Client ID
2. Application type: Web application
3. Authorized redirect URIs: `http://localhost:8000/auth/google/callback`
4. Copy Client ID and Client Secret into `.env`

**JWT Secret** — generate a random 64-character string:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

All other values in `.env.example` work as-is for local development.

---

## Step 2 — Start Infrastructure

```bash
docker compose -f infra/docker/docker-compose.yml up -d
```

This starts:
- **Redis** on port `6379`
- **TimescaleDB** on port `5432`
- **MLflow** UI on port `5001` → open http://localhost:5001 to verify

Wait ~10 seconds for TimescaleDB to initialize, then run the initial migration:

```bash
docker exec -i $(docker ps -qf "name=timescaledb") \
  psql -U trademeter -d trademeter < backend/app/db/migrations/001_initial.sql
```

---

## Step 3 — Backend

```bash
cd backend

# Create and activate virtualenv
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

The API is now at http://localhost:8000. Visit http://localhost:8000/docs for the auto-generated Swagger UI.

---

## Step 4 — Frontend

Open a new terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. You should see the TradeMeter login page.

---

## Step 5 — NinjaTrader Strategy

See [ninja-strategy/README.md](../ninja-strategy/README.md) for the full install guide.

Short version:
1. Copy `ninja-strategy/LiveDataFeedStrategy.cs` into NinjaTrader's custom strategy folder
2. Compile the strategy inside NinjaTrader (NinjaScript Editor → Compile)
3. Add the strategy to a chart
4. Set `ConnectionToken` to the token shown on the TradeMeter **Connect** page

---

## Step 6 — Verify the Connection

1. Log in to TradeMeter at http://localhost:5173
2. Copy your connection token from the **Connect** page
3. Paste the token into the NinjaTrader strategy parameter and enable the strategy
4. Watch the **Dashboard** — live bars and predictions should appear within 1–2 seconds of each new bar

**Backend log to watch:**
```
INFO  tcp_listener: new connection from 127.0.0.1
INFO  tcp_listener: token TM-a3f9x2 resolved to user_id=42
INFO  ingestion: bar received, features computed, pushed to ML pipeline
```

If bars are not appearing, check [docs/AUTH.md](AUTH.md) for token troubleshooting and [ninja-strategy/README.md](../ninja-strategy/README.md) for connection troubleshooting.
