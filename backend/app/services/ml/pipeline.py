"""
ML pipeline orchestrator.

One MLPipeline instance per user.  Holds model instances, XP trackers, drift
detectors, and the Level-3 TradeManager for that user.  Created lazily on first
bar; persisted across requests via the module-level _pipelines dict.

predict_all() → sync River calls, async only for Redis
learn_all()   → update open trades, learn from closed ones, persist results
"""

import asyncio
import json
import logging
import uuid as _uuid
from typing import Optional

import asyncpg
import redis.asyncio as aioredis

from app.core.config import settings
from app.services.ml.models.base import ModelPrediction
from app.services.ml.models.scalper       import ScalperModel
from app.services.ml.models.momentum      import MomentumModel
from app.services.ml.models.mean_reversion import MeanReversionModel
from app.services.ml.models.breakout      import BreakoutModel
from app.services.ml.models.conservative  import ConservativeModel
from app.services.ml.models.aggressive    import AggressiveModel
from app.services.ml.models.volume        import VolumeModel
from app.services.ml.models.contrarian    import ContrarianModel
from app.services.ml.models.personal      import PersonalModel
from app.services.ml.xp                  import XPTracker, LevelUpEvent, level_to_rank
from app.services.ml.drift               import DriftDetector
from app.services.ml.trade_tracker       import TradeManager

logger = logging.getLogger(__name__)

# ── Model registry ─────────────────────────────────────────────────────────

MODEL_REGISTRY: dict[str, type] = {
    "scalper":        ScalperModel,
    "momentum":       MomentumModel,
    "mean_reversion": MeanReversionModel,
    "breakout":       BreakoutModel,
    "conservative":   ConservativeModel,
    "aggressive":     AggressiveModel,
    "volume":         VolumeModel,
    "contrarian":     ContrarianModel,
}

ALL_MODEL_NAMES = list(MODEL_REGISTRY.keys()) + ["personal"]


# ── Pipeline class ─────────────────────────────────────────────────────────

class MLPipeline:
    """Per-user ML state: models, XP trackers, drift detectors, trade manager."""

    def __init__(self, user_id: str, initial_levels: dict) -> None:
        self.user_id = user_id

        self.models: dict[str, object] = {
            name: cls() for name, cls in MODEL_REGISTRY.items()
        }
        self.personal = PersonalModel(user_id)

        # XP tracker per model (loaded from DB on init)
        self.xp_trackers: dict[str, XPTracker] = {
            name: XPTracker(user_id, name, **initial_levels.get(name, {}))
            for name in ALL_MODEL_NAMES
        }

        # Drift detector per model
        self.drift_detectors: dict[str, DriftDetector] = {
            name: DriftDetector(user_id, name)
            for name in ALL_MODEL_NAMES
        }

        # Level rank cache — updated on level-up to avoid repeated lookups
        self.level_ranks: dict[str, str] = {
            name: level_to_rank(self.xp_trackers[name].level)
            for name in ALL_MODEL_NAMES
        }

        # Level 3 trade simulation — one manager per user
        self.trade_manager = TradeManager(user_id)

        self.bar_count = 0

    # ── Prediction ────────────────────────────────────────────────────────

    async def predict_all(
        self,
        features:   dict,
        last_close: float,
    ) -> dict[str, ModelPrediction]:
        """
        Run all 9 models synchronously.
        Contrarian receives other predictions first.
        Personal model receives all 8 personality predictions + level ranks.
        """
        predictions: dict[str, ModelPrediction] = {}

        for name, model in self.models.items():
            if name != "contrarian":
                predictions[name] = model.predict(features, last_close)

        predictions["contrarian"] = self.models["contrarian"].predict(
            features, last_close, other_predictions=predictions
        )

        predictions["personal"] = self.personal.predict(
            features, predictions, self.level_ranks
        )

        return predictions

    # ── Learning ──────────────────────────────────────────────────────────

    async def learn_all(
        self,
        features:     dict,
        actual_close: float,
        prev_close:   float,
        predictions:  dict[str, ModelPrediction],
        bar_high:     float,
        bar_low:      float,
        bar_time:     object,
        db_conn:      asyncpg.Connection,
        redis_client: aioredis.Redis,
    ) -> list[LevelUpEvent]:
        """
        Level 3 learning — called on every bar close.

        Two steps:
        1. Update all open simulated trades with this bar's H/L/C (check target/stop/timeout).
        2. For each trade that closed, call learn_from_trade() and award XP based on P&L.

        Parameters features/prev_close/predictions are kept for API stability but
        are no longer used directly — learning now comes from trade outcomes.
        """
        # ── 1. Update all open trades ──────────────────────────────────────
        closed_trades = self.trade_manager.update_all(
            bar_high, bar_low, actual_close, bar_time
        )

        level_up_events: list[LevelUpEvent] = []

        # ── 2. Learn from closed trades ────────────────────────────────────
        for trade in closed_trades:
            model = self.models.get(trade.model_name) or self.personal
            if model:
                model.learn_from_trade(trade)

            tracker = self.xp_trackers.get(trade.model_name)
            if tracker:
                if trade.won:
                    xp_delta = 10 + int(abs(trade.pnl_points or 0) * 2)
                elif trade.exit_reason == "timeout":
                    xp_delta = 1   # scratch — minimal XP for the bar
                else:
                    xp_delta = -5  # loss penalty

                tracker.xp = max(0, tracker.xp + xp_delta)
                tracker.bars_learned += 1

                event = tracker._check_level_up()
                if event:
                    self.level_ranks[trade.model_name] = event.new_rank
                    level_up_events.append(event)

        # ── 3. Persist levels ──────────────────────────────────────────────
        await self._save_levels(db_conn)

        # ── 4. Save closed trades to DB (non-fatal) ────────────────────────
        for trade in closed_trades:
            await self._save_trade(db_conn, trade)

        # ── 5. MLflow snapshot every N bars ───────────────────────────────
        self.bar_count += 1
        if self.bar_count % settings.model_snapshot_interval == 0:
            await self._snapshot_mlflow()

        return level_up_events

    # ── Persistence ───────────────────────────────────────────────────────

    async def _save_levels(self, db_conn: asyncpg.Connection) -> None:
        uid = _uuid.UUID(self.user_id)
        for name, tracker in self.xp_trackers.items():
            await db_conn.execute(
                """INSERT INTO model_levels
                       (user_id, model_name, level, xp, streak, bars_learned, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, NOW())
                   ON CONFLICT (user_id, model_name)
                   DO UPDATE SET
                       level        = EXCLUDED.level,
                       xp           = EXCLUDED.xp,
                       streak       = EXCLUDED.streak,
                       bars_learned = EXCLUDED.bars_learned,
                       updated_at   = EXCLUDED.updated_at""",
                uid, name,
                tracker.level, tracker.xp, tracker.streak, tracker.bars_learned,
            )

    async def _save_trade(self, db_conn: asyncpg.Connection, trade) -> None:
        """Update the predictions row with P&L outcome from the closed trade."""
        try:
            await db_conn.execute(
                """UPDATE predictions
                   SET actual_outcome = $1,
                       pnl_points     = $2,
                       pnl_dollars    = $3,
                       exit_reason    = $4,
                       bars_held      = $5
                   WHERE user_id    = $6
                     AND model_name = $7
                     AND time       = $8""",
                "win" if trade.won else "loss",
                trade.pnl_points,
                trade.pnl_dollars,
                trade.exit_reason,
                trade.bars_held,
                _uuid.UUID(trade.user_id),
                trade.model_name,
                trade.entry_time,
            )
        except Exception as exc:
            logger.warning("_save_trade failed (non-fatal): %s", exc)

    async def _snapshot_mlflow(self) -> None:
        try:
            import mlflow

            mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
            with mlflow.start_run(run_name=f"trademeter_{self.user_id}_bar{self.bar_count}"):
                for name, model in self.models.items():
                    tracker = self.xp_trackers[name]
                    mlflow.log_metrics({
                        f"{name}_level": tracker.level,
                        f"{name}_bars":  tracker.bars_learned,
                    })
                    mlflow.log_param(f"{name}_rank", self.level_ranks[name])
        except Exception as exc:
            logger.warning("MLflow snapshot failed (non-fatal): %s", exc)


# ── Global per-user registry ───────────────────────────────────────────────

_pipelines: dict[str, MLPipeline] = {}


async def get_pipeline(user_id: str, db_conn: asyncpg.Connection) -> MLPipeline:
    """
    Return existing pipeline for user or create a fresh one.
    Always returns a valid MLPipeline — never raises.
    On creation, attempts to load XP levels from DB; uses empty defaults on failure.
    """
    if user_id in _pipelines:
        return _pipelines[user_id]

    try:
        rows = await db_conn.fetch(
            """SELECT model_name, level, xp, streak, bars_learned
               FROM   model_levels
               WHERE  user_id = $1""",
            _uuid.UUID(user_id),
        )
        initial_levels = {
            r["model_name"]: {
                "level":        r["level"],
                "xp":           r["xp"],
                "streak":       r["streak"],
                "bars_learned": r["bars_learned"],
            }
            for r in rows
        }
    except Exception as exc:
        logger.warning("get_pipeline: could not load model levels for %s (%s) — using defaults", user_id, exc)
        initial_levels = {}

    pipeline = MLPipeline(user_id, initial_levels)
    _pipelines[user_id] = pipeline
    logger.info("ML pipeline created for user %s", user_id)
    return pipeline
