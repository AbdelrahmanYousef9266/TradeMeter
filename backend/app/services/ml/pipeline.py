"""
ML pipeline orchestrator — Phase 6A with Champion/Challenger.

One MLPipeline instance per user.  Each of the 8 personality models is wrapped
in a ChampionChallenger instance that runs a silent Challenger alongside the
live-serving Champion.  Every 100 bars the better P&L wins.

Personal model (model 9) is kept as-is — no CC wrapper needed.

predict_all() → Champion predictions + opens simulated trades (async for convenience)
learn_all()   → updates open trades, learns from closed ones, checks CC evaluations
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
from app.services.ml.champion_challenger import ChampionChallenger

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
    """Per-user ML state: CC models, XP trackers, drift detectors, trade manager."""

    def __init__(self, user_id: str, initial_levels: dict) -> None:
        self.user_id = user_id

        # Wrap each personality model in Champion/Challenger
        self.cc_models: dict[str, ChampionChallenger] = {}
        for name, cls in MODEL_REGISTRY.items():
            base_instance  = cls()
            initial_params = base_instance.get_settings()
            self.cc_models[name] = ChampionChallenger(name, cls, initial_params)

        # Personal model — no CC, keeps its own blend logic
        self.personal = PersonalModel(user_id)

        # XP tracker per model
        self.xp_trackers: dict[str, XPTracker] = {
            name: XPTracker(user_id, name, **initial_levels.get(name, {}))
            for name in ALL_MODEL_NAMES
        }

        # Drift detectors (kept for API compatibility; not actively used in CC mode)
        self.drift_detectors: dict[str, DriftDetector] = {
            name: DriftDetector(user_id, name)
            for name in ALL_MODEL_NAMES
        }

        # Level rank cache
        self.level_ranks: dict[str, str] = {
            name: level_to_rank(self.xp_trackers[name].level)
            for name in ALL_MODEL_NAMES
        }

        self.trade_manager = TradeManager(user_id)
        self.bar_count = 0

    # ── Prediction ────────────────────────────────────────────────────────

    async def predict_all(
        self,
        features:      dict,
        last_close:    float,
        next_bar_open: Optional[float] = None,
        bar_time:      Optional[object] = None,
    ) -> dict[str, ModelPrediction]:
        """
        Run all 9 models.  Champion predictions go to dashboard.
        Challenger predictions run silently for warmup.

        If next_bar_open and bar_time are provided, opens simulated trades
        for every non-HOLD signal using the Champion's ATR multipliers.
        """
        predictions: dict[str, ModelPrediction] = {}

        for name, cc in self.cc_models.items():
            if name != "contrarian":
                predictions[name] = cc.predict(features, last_close)

        # Contrarian gets other predictions so it can invert the consensus
        predictions["contrarian"] = self.cc_models["contrarian"].predict(
            features, last_close, other_predictions=predictions
        )

        # Personal blends all 8 champion signals
        predictions["personal"] = self.personal.predict(
            features, predictions, self.level_ranks
        )

        # Open simulated trades for non-HOLD signals
        if next_bar_open is not None and bar_time is not None:
            atr = features.get("atr_14", 1.0)
            for name, pred in predictions.items():
                if pred.signal != "HOLD":
                    cc = self.cc_models.get(name)
                    if cc:
                        params = cc.champion.params
                    else:
                        params = self.personal.get_settings()
                    self.trade_manager.open_trade(
                        model_name      = name,
                        signal          = pred.signal,
                        next_bar_open   = next_bar_open,
                        atr             = atr,
                        atr_stop_mult   = params.get("atr_stop_mult",   1.5),
                        atr_target_mult = params.get("atr_target_mult", 3.0),
                        confidence      = pred.confidence,
                        features        = features,
                        bar_time        = bar_time,
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
        Phase 6A learning:
        1. Update open simulated trades (check target/stop/timeout)
        2. For each closed trade: CC.learn() + XP award
        3. Check CC evaluations every 100 bars (may promote Challenger)
        4. Persist levels and promotions
        """
        # ── 1. Update open trades ─────────────────────────────────────────
        closed_trades = self.trade_manager.update_all(
            bar_high, bar_low, actual_close, bar_time
        )

        level_up_events: list[LevelUpEvent] = []

        # ── 2. Learn from closed trades ────────────────────────────────────
        for trade in closed_trades:
            trade_outcome = {
                "signal":      trade.signal,
                "features":    trade.features,
                "pnl_points":  trade.pnl_points or 0.0,
                "won":         trade.won,
                "exit_price":  trade.exit_price,
                "exit_reason": trade.exit_reason,
            }

            if trade.model_name == "personal":
                self.personal.learn_from_bar(
                    trade.features, 1 if trade.won else 0, {}
                )
            else:
                cc = self.cc_models.get(trade.model_name)
                if cc:
                    cc.learn(trade_outcome)

            tracker = self.xp_trackers.get(trade.model_name)
            if tracker:
                if trade.won:
                    tracker.streak += 1
                    tracker.xp = max(0, tracker.xp + 10 + int(abs(trade.pnl_points or 0) * 2))
                elif trade.exit_reason == "timeout":
                    tracker.xp = max(0, tracker.xp + 1)
                    # Timeout is neutral — streak unchanged
                else:
                    tracker.streak = 0
                    tracker.xp = max(0, tracker.xp - 5)
                tracker.bars_learned += 1

                event = tracker._check_level_up()
                if event:
                    self.level_ranks[trade.model_name] = event.new_rank
                    level_up_events.append(event)

            await self._save_trade(db_conn, trade)

        # ── 3. Champion/Challenger evaluations ─────────────────────────────
        for name, cc in self.cc_models.items():
            promotion = cc.maybe_evaluate()
            if promotion:
                try:
                    await redis_client.publish(
                        f"live:{self.user_id}",
                        json.dumps({
                            "type":           "cc_promotion",
                            "model_name":     promotion.model_name,
                            "winner":         promotion.winner,
                            "champion_pnl":   round(promotion.champion_pnl, 2),
                            "challenger_pnl": round(promotion.challenger_pnl, 2),
                            "new_params":     promotion.new_params,
                            "old_params":     promotion.old_params,
                        })
                    )
                except Exception:
                    pass
                await self._save_promotion(db_conn, promotion)

        # ── 4. Persist levels ──────────────────────────────────────────────
        await self._save_levels(db_conn)

        self.bar_count += 1
        if self.bar_count % settings.model_snapshot_interval == 0:
            await self._snapshot_mlflow()

        return level_up_events

    def get_cc_status(self) -> dict:
        """Returns CC status for all 8 personality models."""
        return {name: cc.get_status() for name, cc in self.cc_models.items()}

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

    async def _save_promotion(self, db_conn: asyncpg.Connection, promotion) -> None:
        try:
            import json as _json
            await db_conn.execute(
                """INSERT INTO cc_history
                       (user_id, model_name, winner, champion_pnl, challenger_pnl,
                        old_params, new_params, bars_evaluated)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)""",
                _uuid.UUID(self.user_id),
                promotion.model_name,
                promotion.winner,
                promotion.champion_pnl,
                promotion.challenger_pnl,
                _json.dumps(promotion.old_params),
                _json.dumps(promotion.new_params),
                promotion.bars_evaluated,
            )
        except Exception as exc:
            logger.warning("_save_promotion failed (non-fatal): %s", exc)

    async def _snapshot_mlflow(self) -> None:
        try:
            import mlflow
            mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
            with mlflow.start_run(run_name=f"trademeter_{self.user_id}_bar{self.bar_count}"):
                for name, tracker in self.xp_trackers.items():
                    mlflow.log_metrics({
                        f"{name}_level": tracker.level,
                        f"{name}_bars":  tracker.bars_learned,
                    })
                    mlflow.log_param(f"{name}_rank", self.level_ranks[name])
        except Exception as exc:
            logger.warning("MLflow snapshot failed (non-fatal): %s", exc)


# ── Global per-user registry ───────────────────────────────────────────────

_pipelines: dict[str, MLPipeline] = {}
_pipeline_locks: dict[str, asyncio.Lock] = {}


async def get_pipeline(user_id: str, db_conn: asyncpg.Connection) -> MLPipeline:
    # Fast path — no lock needed for reads once the pipeline exists
    if user_id in _pipelines:
        return _pipelines[user_id]

    # Ensure a per-user lock exists (synchronous, atomic in asyncio — no await between
    # the check and the assignment so no race on lock creation itself)
    if user_id not in _pipeline_locks:
        _pipeline_locks[user_id] = asyncio.Lock()

    async with _pipeline_locks[user_id]:
        # Re-check inside the lock: another coroutine may have created the
        # pipeline while we were waiting to acquire the lock
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
