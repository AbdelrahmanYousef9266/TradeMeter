"""
ML pipeline orchestrator.

One MLPipeline instance per user.  Holds model instances, XP trackers, and drift
detectors for that user.  Created lazily on first bar for that user; persisted
across requests via the module-level _pipelines dict.

predict_all() → sync River calls, async only for Redis
learn_all()   → sync River calls + async DB/Redis persistence
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
    """Per-user ML state: models, XP trackers, drift detectors."""

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

        self.bar_count = 0
        self.prev_pnl  = 0.0

    # ── Prediction ────────────────────────────────────────────────────────

    async def predict_all(
        self,
        features:   dict,
        last_close: float,
    ) -> dict[str, ModelPrediction]:
        """
        Run all 10 models synchronously; the async wrapper is for call-site
        convenience (callers are already async for DB/Redis work).

        Contrarian receives other predictions first.
        Personal model receives all 8 personality predictions + level ranks.
        """
        predictions: dict[str, ModelPrediction] = {}

        # 7 non-contrarian models first
        for name, model in self.models.items():
            if name != "contrarian":
                predictions[name] = model.predict(features, last_close)

        # Contrarian with majority context
        predictions["contrarian"] = self.models["contrarian"].predict(
            features, last_close, other_predictions=predictions
        )

        # Personal blends all 8
        predictions["personal"] = self.personal.predict(
            features, predictions, self.level_ranks
        )

        return predictions

    # ── Learning ──────────────────────────────────────────────────────────

    async def learn_all(
        self,
        features:        dict,
        actual_close:    float,
        prev_close:      float,
        predictions:     dict[str, ModelPrediction],
        db_conn:         asyncpg.Connection,
        redis_client:    aioredis.Redis,
    ) -> list[LevelUpEvent]:
        """
        Called when the NEXT bar closes.
        Updates model weights, awards XP, checks for level-ups, persists results.
        """
        actual_direction = 1 if actual_close > prev_close else 0
        curr_pnl = (actual_close - prev_close) / prev_close if prev_close else 0.0

        # Labels for regression targets (approximate from close)
        label_high = actual_close * 1.002
        label_low  = actual_close * 0.998

        level_up_events: list[LevelUpEvent] = []

        # ── Personality models ─────────────────────────────────────────
        correct_by_model: dict[str, bool] = {}

        for name, model in self.models.items():
            pred = predictions.get(name)
            if pred is None:
                continue

            model.learn(features, actual_direction, label_high, label_low)

            correct = (pred.direction_up > 0.5) == bool(actual_direction)
            correct_by_model[name] = correct

            if self.drift_detectors[name].update(correct):
                logger.info("Drift detected for %s user=%s — resetting weights", name, self.user_id)
                model.reset()
                self.xp_trackers[name].streak = 0
                try:
                    await redis_client.publish(
                        f"live:{self.user_id}",
                        json.dumps({"type": "drift", "model": name}),
                    )
                except Exception:
                    pass

            event = self.xp_trackers[name].award(
                pred.direction_up, actual_direction, self.prev_pnl, curr_pnl
            )
            if event:
                self.level_ranks[name] = event.new_rank
                level_up_events.append(event)

        # ── Personal model ─────────────────────────────────────────────
        pred_personal = predictions.get("personal")
        if pred_personal:
            self.personal.learn_from_bar(features, actual_direction, correct_by_model)

            correct_p = (pred_personal.direction_up > 0.5) == bool(actual_direction)
            if self.drift_detectors["personal"].update(correct_p):
                self.personal.reset()
                self.xp_trackers["personal"].streak = 0

            event = self.xp_trackers["personal"].award(
                pred_personal.direction_up, actual_direction, self.prev_pnl, curr_pnl
            )
            if event:
                self.level_ranks["personal"] = event.new_rank
                level_up_events.append(event)

        # ── Persist levels to DB ───────────────────────────────────────
        await self._save_levels(db_conn)

        # ── MLflow snapshot every N bars ───────────────────────────────
        self.bar_count += 1
        if self.bar_count % settings.model_snapshot_interval == 0:
            await self._snapshot_mlflow()

        self.prev_pnl = curr_pnl
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

    async def _snapshot_mlflow(self) -> None:
        try:
            import mlflow
            import pickle

            mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
            with mlflow.start_run(run_name=f"trademeter_{self.user_id}_bar{self.bar_count}"):
                for name, model in self.models.items():
                    tracker = self.xp_trackers[name]
                    mlflow.log_metrics({
                        f"{name}_level":    tracker.level,
                        f"{name}_bars":     tracker.bars_learned,
                    })
                    mlflow.log_param(f"{name}_rank", self.level_ranks[name])
        except Exception as exc:
            logger.warning("MLflow snapshot failed (non-fatal): %s", exc)


# ── Global per-user registry ───────────────────────────────────────────────

_pipelines: dict[str, MLPipeline] = {}


async def get_pipeline(user_id: str, db_conn: asyncpg.Connection) -> MLPipeline:
    """
    Return existing pipeline for user or create a fresh one.
    On creation, loads existing XP levels from TimescaleDB.
    """
    if user_id in _pipelines:
        return _pipelines[user_id]

    rows = await db_conn.fetch(
        """SELECT model_name, level, xp, streak, bars_learned
           FROM   model_levels
           WHERE  user_id = $1""",
        _uuid.UUID(user_id),
    )
    initial_levels = {r["model_name"]: dict(r) for r in rows}
    pipeline = MLPipeline(user_id, initial_levels)
    _pipelines[user_id] = pipeline
    logger.info("ML pipeline created for user %s", user_id)
    return pipeline
