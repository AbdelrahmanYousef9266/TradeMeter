"""
TradeMeter FastAPI application entry point.

Startup sequence (lifespan):
  1. Create asyncpg connection pool and run DB migrations
  2. Connect to Redis
  3. Start TCP listener (background task)
  4. Start Redis Stream ingestion consumer (background task)

Shutdown sequence:
  1. Cancel background tasks
  2. Close Redis connection
  3. Close DB pool
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.redis import create_redis_client
from app.db.database import create_pool, init_db
from app.services.market_data.ingestion import consume_stream
from app.services.market_data.tcp_listener import start_tcp_server
from app.api.routes.auth import router as auth_router
from app.api.routes.market import router as market_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    logger.info("Starting TradeMeter backend (env=%s)", settings.env)

    app.state.db_pool = await create_pool()
    await init_db(app.state.db_pool)

    app.state.redis = await create_redis_client()

    app.state.tcp_task = asyncio.create_task(
        start_tcp_server(
            settings.nt_tcp_host,
            settings.nt_tcp_port,
            db_pool=app.state.db_pool,
            redis_client=app.state.redis,
        )
    )

    app.state.ingestion_task = asyncio.create_task(
        consume_stream(
            redis_client=app.state.redis,
            db_pool=app.state.db_pool,
        )
    )

    logger.info("TradeMeter backend ready")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("Shutting down TradeMeter backend")

    for task in (app.state.tcp_task, app.state.ingestion_task):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    await app.state.redis.aclose()
    await app.state.db_pool.close()

    logger.info("Shutdown complete")


app = FastAPI(
    title="TradeMeter",
    description="Live ML-powered trading dashboard for NinjaTrader 8",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,   prefix="/auth",   tags=["auth"])
app.include_router(market_router, prefix="/market", tags=["market"])


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Simple liveness probe — returns 200 if the process is running."""
    return {"status": "ok", "version": app.version}
