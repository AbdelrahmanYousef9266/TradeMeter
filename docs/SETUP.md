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

**Google OAuth credentials** — from [Google Cloud Console](https://console.cloud.google.com):
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
- **MLflow** on port `5001` → open http://localhost:5001 to verify

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

On first startup:
- All 10 River models are initialized with empty weights and begin learning immediately from the first bar
- Each user's personal model (Model 9 or 10) is created automatically on first login
- The `create_hypertable()` call in `database.py` is safe to run multiple times (no-op if already created)

Visit http://localhost:8000/docs for the auto-generated Swagger UI.

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
2. Compile inside NinjaTrader (NinjaScript Editor → Compile)
3. Add the strategy to a MES chart
4. Set `ConnectionToken` to the token shown on the TradeMeter **Connect** page after logging in

The strategy sends bars in the format:
```
TOKEN|TIMESTAMP|SYMBOL|OPEN|HIGH|LOW|CLOSE|VOLUME|BAR_TYPE\n
```

---

## Step 6 — Verify the Connection

1. Log in to TradeMeter at http://localhost:5173
2. Copy your connection token from the **Connect** page
3. Paste into the NinjaTrader strategy `ConnectionToken` parameter and enable the strategy
4. Watch the **Dashboard** — all 10 model cards should begin populating with signals within 1–2 bars

**Backend log to watch:**
```
INFO  tcp_listener: new connection from 127.0.0.1
INFO  tcp_listener: token validated → user_id=<uuid>
INFO  ingestion: bar received, features computed, 10 models updated
INFO  ws_broadcaster: pushed bar + signals to 1 client(s)
```

---

## Giving Your Brother Access

Two options:

### Option A — Deploy to a cloud server (recommended for permanent use)

Deploy the Docker Compose stack to any VPS (DigitalOcean, Hetzner, etc.). Both you and your brother log in via your own Google accounts and get separate tokens. Each points their NinjaTrader to the server's IP on port 5000.

### Option B — Tailscale (for local/dev use)

1. Install [Tailscale](https://tailscale.com) on your machine and your brother's machine
2. Both join the same Tailscale network
3. Brother's NinjaTrader sets the TradeMeter server address to your Tailscale IP (e.g. `100.x.x.x`) port 5000
4. He logs into TradeMeter via your Tailscale IP in his browser
5. Each gets a separate Google login and separate token — all data is still fully isolated

---

## MLflow UI

MLflow runs at http://localhost:5001. View model snapshots, accuracy metrics, and drift events per model per user. Each snapshot is tagged with `user_id` and `model_name` so you can drill down to any individual model's training history and roll back if needed.
