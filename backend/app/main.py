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
from app.api.routes.auth                import router as auth_router
from app.api.routes.market              import router as market_router
from app.api.routes.predictions         import router as predictions_router
from app.api.routes.models              import router as models_router
from app.api.routes.champion_challenger import router as cc_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def nightly_lstm_training(app: FastAPI) -> None:
    """
    Retrain the LSTM (Model 11) for every active user once per day, ~2 AM ET.

    Checks hourly; trains when the UTC hour is 7 (≈2 AM ET, ±1h for DST).
    Only users with at least MIN_BARS_TO_ACTIVATE bars are trained.
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.services.ml.lstm_trainer import train_lstm, count_available_bars
    from app.services.ml.lstm_model import MIN_BARS_TO_ACTIVATE
    from app.services.ml.pipeline import _pipelines

    while True:
        try:
            await asyncio.sleep(3600)  # check hourly

            now = datetime.now(timezone.utc)
            if now.hour != 7:           # ~2 AM ET
                continue

            for user_id in list(_pipelines.keys()):
                try:
                    async with app.state.db_pool.acquire() as conn:
                        bars = await count_available_bars(conn, user_id)
                        if bars < MIN_BARS_TO_ACTIVATE:
                            continue
                        logger.info("Nightly LSTM training for user %s (%d bars)…", user_id, bars)
                        result = await train_lstm(conn, user_id)
                        logger.info("Nightly LSTM result for %s: %s", user_id, result)

                        pipeline = _pipelines.get(user_id)
                        if pipeline and result.get("success"):
                            row = await conn.fetchrow(
                                "SELECT state FROM model_state WHERE user_id=$1 AND model_name='lstm'",
                                _uuid.UUID(user_id),
                            )
                            if row:
                                pipeline.lstm.load(row["state"])
                except Exception as exc:
                    logger.error("Nightly LSTM training failed for %s: %s", user_id, exc)

        except asyncio.CancelledError:
            logger.info("Nightly LSTM training task cancelled")
            break
        except Exception as exc:
            logger.error("Nightly LSTM training loop error: %s", exc)


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

    app.state.lstm_task = asyncio.create_task(nightly_lstm_training(app))

    logger.info("TradeMeter backend ready")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("Shutting down TradeMeter backend")

    # Stop ingesting first so no pipeline is mutated while we snapshot it.
    for task in (app.state.tcp_task, app.state.ingestion_task, app.state.lstm_task):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    # Persist learned model weights for every active pipeline so a restart
    # resumes learning instead of starting from scratch.
    try:
        from app.services.ml.pipeline import _pipelines
        if _pipelines:
            async with app.state.db_pool.acquire() as conn:
                for pl in list(_pipelines.values()):
                    await pl.save_state(conn)
            logger.info("Persisted model state for %d pipeline(s) on shutdown", len(_pipelines))
    except Exception as exc:
        logger.error("Failed to persist model state on shutdown: %s", exc)

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

app.include_router(auth_router,         prefix="/auth",        tags=["auth"])
app.include_router(market_router,       prefix="/market",      tags=["market"])
app.include_router(predictions_router,  prefix="/predictions", tags=["predictions"])
app.include_router(models_router,       prefix="/models",      tags=["models"])
app.include_router(cc_router,           prefix="/cc",          tags=["champion-challenger"])


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Simple liveness probe — returns 200 if the process is running."""
    return {"status": "ok", "version": app.version}
