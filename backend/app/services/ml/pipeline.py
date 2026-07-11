"""
ML pipeline orchestrator — Phase 6A with Champion/Challenger.

One MLPipeline instance per user.  Each of the 8 personality models is wrapped
in a ChampionChallenger instance that runs a silent Challenger alongside the
live-serving Champion.  Every 100 bars the better P&L wins.

Personal model (model 9) is kept as-is — no CC wrapper needed.

predict_all() → Champion predictions; buffers signals to open at the NEXT bar's
                open (both a live Champion book and a silent Challenger book)
learn_all()   → updates open trades, learns from closed ones, checks CC evaluations
"""

import asyncio
import json
import logging
import pickle
import uuid as _uuid
from typing import Optional

import asyncpg
import redis.asyncio as aioredis

from app.core.config import settings
from app.services.market_data.features import get_et_time
from app.services.ml.models.base import ModelPrediction, ml_features
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
from app.services.ml.lstm_model          import LSTMModel

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

# The batch-trained LSTM (Model 11) runs on the 5-min timeframe ONLY (it is the
# primary trading timeframe). The 8 CC personality models + personal run on EVERY
# timeframe. So per timeframe: 1-min → 9 online models (no lstm); 5-min → the same
# 9 online models + lstm.
LSTM_TIMEFRAME = "5min"

# 9 online models present on both timeframes (8 CC personalities + personal).
ONLINE_MODEL_NAMES = list(MODEL_REGISTRY.keys()) + ["personal"]

# Full superset (5-min set): 9 online + lstm. Kept as ALL_MODEL_NAMES for
# backward compatibility with callers/tests that want "every model name".
ALL_MODEL_NAMES = ONLINE_MODEL_NAMES + ["lstm"]


def model_names_for(timeframe: str) -> list[str]:
    """Model names that run on a timeframe: lstm only on the 5-min series."""
    if timeframe == LSTM_TIMEFRAME:
        return ONLINE_MODEL_NAMES + ["lstm"]
    return list(ONLINE_MODEL_NAMES)


# ── Pipeline class ─────────────────────────────────────────────────────────

class MLPipeline:
    """Per-(user, timeframe) ML state: CC models, XP trackers, drift detectors,
    trade managers. Each timeframe is a fully independent set of models — the
    5-min Momentum and the 1-min Momentum are separate competitors with their own
    weights, XP, trades, and persistence. The default timeframe is the primary
    trading timeframe (5-min), which carries the full model set including lstm."""

    def __init__(self, user_id: str, initial_levels: dict, timeframe: str = "5min",
                 context: str = "live") -> None:
        self.user_id = user_id
        self.timeframe = timeframe
        # context ∈ {"live","offline"}. 'live' serves live trading and learns only
        # from live bars; 'offline' is an independent COPY trained on history that
        # never mutates live and is merged in only via explicit promotion. All
        # persistence below is scoped by this context so the two never collide.
        self.context = context
        self.model_names = model_names_for(timeframe)
        self._has_lstm = "lstm" in self.model_names

        # Wrap each personality model in Champion/Challenger (both timeframes)
        self.cc_models: dict[str, ChampionChallenger] = {}
        for name, cls in MODEL_REGISTRY.items():
            base_instance  = cls()
            initial_params = base_instance.get_settings()
            self.cc_models[name] = ChampionChallenger(name, cls, initial_params)

        # Personal model — no CC, keeps its own blend logic (both timeframes)
        self.personal = PersonalModel(user_id)

        # LSTM (Model 11) — 5-min only. Batch-trained, inference-only, no CC.
        # Loads its trained weights from model_state in get_pipeline().
        self.lstm = LSTMModel(user_id) if self._has_lstm else None

        # XP tracker per model on THIS timeframe
        self.xp_trackers: dict[str, XPTracker] = {
            name: XPTracker(user_id, name, **initial_levels.get(name, {}))
            for name in self.model_names
        }

        # Drift detectors (kept for API compatibility; not actively used in CC mode)
        self.drift_detectors: dict[str, DriftDetector] = {
            name: DriftDetector(user_id, name)
            for name in self.model_names
        }

        # Level rank cache
        self.level_ranks: dict[str, str] = {
            name: level_to_rank(self.xp_trackers[name].level)
            for name in self.model_names
        }

        # Champion (live) trade book — its outcomes drive the dashboard + XP.
        self.trade_manager = TradeManager(user_id)
        # Challenger (silent) shadow book — lets each Challenger accumulate its
        # OWN P&L from its OWN signals so it can genuinely out/under-perform the
        # Champion. Without this the two P&Ls are identical and no promotion can
        # ever happen.
        self.challenger_trade_manager = TradeManager(user_id)

        # Signals buffered this bar, opened at the NEXT bar's real open (see
        # predict_all). Filling at the current bar's open while the signal was
        # derived from the current bar's close would be look-ahead bias.
        self._pending_champion:   list[dict] = []
        self._pending_challenger: list[dict] = []

        # ET calendar date of the last bar seen — used to detect an RTH session
        # rollover so each model's per-session signal budget is cleared once a day
        # (see _maybe_reset_session). Without this the max_signals_per_session cap,
        # once hit, never reset and every later bar force-HOLD'd.
        self._last_session_date = None

        self.bar_count = 0

    # ── Per-session signal-budget reset ─────────────────────────────────────

    def _maybe_reset_session(self, bar_time: object) -> None:
        """
        Clear every model's per-session signal counter when a new RTH session
        (ET calendar day) begins. The models expose reset_session() for exactly
        this, but nothing was wired to call it — so a model that spent its
        max_signals_per_session budget stayed capped for the rest of the run,
        emitting HOLD at full confidence forever. Detect the ET date changing and
        reset the budget on the Champion, Challenger, and personal models.
        """
        if bar_time is None:
            return
        try:
            d = get_et_time(bar_time).date()
        except Exception:
            return
        if self._last_session_date is None:
            self._last_session_date = d
            return
        if d == self._last_session_date:
            return
        self._last_session_date = d
        for cc in self.cc_models.values():
            for model_obj in (cc._champion_model_obj, cc._challenger_model_obj):
                reset = getattr(model_obj, "reset_session", None)
                if callable(reset):
                    reset()
        reset_personal = getattr(self.personal, "reset_session", None)
        if callable(reset_personal):
            reset_personal()

    # ── Prediction ────────────────────────────────────────────────────────

    async def predict_all(
        self,
        features:         dict,
        last_close:       float,
        current_bar_open: Optional[float] = None,
        bar_time:         Optional[object] = None,
    ) -> dict[str, ModelPrediction]:
        """
        Run all 9 models.  Champion predictions go to dashboard.
        Challenger predictions run silently and open their own shadow trades.

        Trade-entry timing (look-ahead-free):
          `current_bar_open` is the open of the bar being processed NOW. Signals
          buffered on the *previous* bar are filled at this open (the genuinely
          next bar after the signal), then this bar's signals are buffered to be
          filled at the *next* bar's open. A signal derived from a bar's close
          must never fill at that same bar's open.
        """
        # Clear the per-session signal budget at the start of each new RTH day.
        self._maybe_reset_session(bar_time)

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

        # LSTM (Model 11, 5-min only) — inference only. Feeds its rolling window
        # every bar (even when dormant) and returns HOLD until trained + window
        # full. Absent on the 1-min pipeline.
        if self.lstm is not None:
            predictions["lstm"] = self.lstm.predict(features, last_close)

        if current_bar_open is not None and bar_time is not None:
            # 1. Fill signals buffered on the PREVIOUS bar at THIS bar's real open.
            self._fill_pending_trades(current_bar_open, bar_time)
            # 2. Buffer THIS bar's signals — they fill at the NEXT bar's open.
            self._buffer_pending_trades(predictions, features, bar_time)

        return predictions

    # ── Trade-entry buffering (deferred fill — avoids look-ahead) ───────────

    def _fill_pending_trades(self, bar_open: float, bar_time: object) -> None:
        """
        Open all buffered signals at *bar_open* (the actual next-bar open, so the
        fill price is look-ahead-free).  The trade's entry_time is set to the
        SIGNAL bar's time (buffered as `signal_time`), not this fill bar, so
        _save_trade attributes the realized P&L to the prediction row that
        actually produced the signal — one bar earlier — rather than to this
        bar's (unrelated) prediction.
        """
        for spec in self._pending_champion:
            signal_time = spec.pop("signal_time", bar_time)
            self.trade_manager.open_trade(next_bar_open=bar_open, bar_time=signal_time, **spec)
        self._pending_champion = []

        for spec in self._pending_challenger:
            signal_time = spec.pop("signal_time", bar_time)
            self.challenger_trade_manager.open_trade(next_bar_open=bar_open, bar_time=signal_time, **spec)
        self._pending_challenger = []

    def _buffer_pending_trades(self, predictions: dict, features: dict, signal_time: object) -> None:
        """Record this bar's non-HOLD signals for filling at the next bar's open."""
        atr = features.get("atr_14", 1.0)

        # Champion book: all live models (8 CC + personal + lstm).
        for name, pred in predictions.items():
            if pred.signal == "HOLD":
                continue
            cc     = self.cc_models.get(name)
            params = cc.champion.params if cc else self.personal.get_settings()
            self._pending_champion.append({
                "model_name":      name,
                "signal":          pred.signal,
                "atr":             atr,
                "atr_stop_mult":   params.get("atr_stop_mult",   1.5),
                "atr_target_mult": params.get("atr_target_mult", 3.0),
                "confidence":      pred.confidence,
                "features":        features,
                "signal_time":     signal_time,
            })

        # Challenger book: the 8 CC models' own (silent) signals.
        for name, cc in self.cc_models.items():
            cpred = getattr(cc, "last_challenger_pred", None)
            if cpred is None or cpred.signal == "HOLD":
                continue
            params = cc.challenger.params
            self._pending_challenger.append({
                "model_name":      name,
                "signal":          cpred.signal,
                "atr":             atr,
                "atr_stop_mult":   params.get("atr_stop_mult",   1.5),
                "atr_target_mult": params.get("atr_target_mult", 3.0),
                "confidence":      cpred.confidence,
                "features":        features,
                "signal_time":     signal_time,
            })

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
        fast_mode:    bool = False,
    ) -> list[LevelUpEvent]:
        """
        Two-layer learning:
        1. Baseline (every bar): each model learns the realized direction, so
           bars_learned advances every bar and the classifiers escape the
           "HOLD 50%" deadlock (HOLD → no trades → no closes → no learning).
        2. Refinement (on trade close): P&L-based learning + bonus XP.
        3. Check CC evaluations every 100 bars (may promote Challenger).
        4. Persist levels and promotions.

        fast_mode (bulk historical import): keep ALL the in-memory learning
        (River learn_one, XP, trades, CC evaluation) but skip every per-bar side
        effect — trade-row updates, promotion broadcast/persist, per-bar level
        persistence, MLflow snapshot, and periodic weight save. The caller
        persists levels + weights once per batch instead. db_conn may be None.
        """
        # ── 1. Update open trades ─────────────────────────────────────────
        closed_trades = self.trade_manager.update_all(
            bar_high, bar_low, actual_close, bar_time
        )

        level_up_events: list[LevelUpEvent] = []

        # ── 2. Baseline per-bar learning (Level 1) ─────────────────────────
        # Every learning model trains on the realized direction on EVERY bar.
        # `features` is the PREVIOUS bar's feature vector (the inputs that
        # produced `predictions`); actual_direction is what price then did.
        actual_direction = 1 if actual_close > prev_close else 0

        for name, cc in self.cc_models.items():
            # Train both Champion and Challenger classifiers on the realized
            # direction — this is what moves them off the default 0.5 output.
            for model_obj in (cc._champion_model_obj, cc._challenger_model_obj):
                try:
                    model_obj.classifier.learn_one(ml_features(features), actual_direction)
                except Exception:
                    pass
            self._baseline_award(name, predictions.get(name), actual_direction, level_up_events)

        # Personal model — baseline direction learning + XP
        try:
            self.personal.learn_from_bar(features, actual_direction, {})
        except Exception:
            pass
        self._baseline_award("personal", predictions.get("personal"), actual_direction, level_up_events)

        # LSTM (Model 11) is batch-trained, not online — it has no per-bar weights
        # to update here. Advance its bars_learned/XP only once it is actually
        # trained and predicting live, so the dashboard reflects real activity
        # instead of a frozen 0 (and no phantom bars accrue while it is dormant).
        if self.lstm is not None and self.lstm.is_trained:
            self._baseline_award("lstm", predictions.get("lstm"), actual_direction, level_up_events)

        # ── 3. Trade-close refinement (Level 3 P&L) ────────────────────────
        # bars_learned and streak are owned by the baseline above; this layer
        # only adds P&L-based classifier learning and bonus XP.
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
                    cc.learn_champion(trade_outcome)

            tracker = self.xp_trackers.get(trade.model_name)
            if tracker:
                if trade.won:
                    tracker.xp = max(0, tracker.xp + 10 + int(abs(trade.pnl_points or 0) * 2))
                elif trade.exit_reason != "timeout":
                    tracker.xp = max(0, tracker.xp - 5)
                # timeout is neutral — no XP change

                event = tracker._check_level_up()
                if event:
                    self.level_ranks[trade.model_name] = event.new_rank
                    level_up_events.append(event)

            if not fast_mode:
                await self._save_trade(db_conn, trade)

        # ── 3b. Challenger shadow-book refinement (silent) ─────────────────
        # The Challenger's own trades close here and feed ONLY the Challenger
        # model + its P&L tally. No XP, no DB rows — it never touches the
        # dashboard until (and unless) it wins an evaluation and is promoted.
        challenger_closed = self.challenger_trade_manager.update_all(
            bar_high, bar_low, actual_close, bar_time
        )
        for trade in challenger_closed:
            cc = self.cc_models.get(trade.model_name)
            if cc:
                cc.learn_challenger({
                    "signal":      trade.signal,
                    "features":    trade.features,
                    "pnl_points":  trade.pnl_points or 0.0,
                    "won":         trade.won,
                    "exit_price":  trade.exit_price,
                    "exit_reason": trade.exit_reason,
                })

        # ── 4. Champion/Challenger evaluations ─────────────────────────────
        for name, cc in self.cc_models.items():
            promotion = cc.maybe_evaluate()
            if promotion and not fast_mode:
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

        self.bar_count += 1

        # ── 5. Persist levels ──────────────────────────────────────────────
        # In fast (bulk-import) mode the caller persists levels + weights once
        # per batch, so skip all per-bar persistence here.
        if not fast_mode:
            await self._save_levels(db_conn)
            if self.bar_count % settings.model_snapshot_interval == 0:
                await self._snapshot_mlflow()
            if self.bar_count % settings.model_state_save_interval == 0:
                await self.save_state(db_conn)

        return level_up_events

    def _baseline_award(
        self,
        name: str,
        pred: Optional[ModelPrediction],
        actual_direction: int,
        level_up_events: list,
    ) -> None:
        """
        Award baseline per-bar XP for one model via the Level-1 award logic
        (handles base XP, direction-correctness XP, streak, bars_learned, and
        level-up). Called on every bar so bars_learned always advances.
        """
        tracker = self.xp_trackers.get(name)
        if not tracker:
            return
        if pred is not None:
            event = tracker.award(pred.direction_up, actual_direction, 0.0, 0.0)
        else:
            # No prior prediction to score — still count the bar as learned
            tracker.bars_learned += 1
            event = tracker._check_level_up()
        if event:
            self.level_ranks[name] = event.new_rank
            level_up_events.append(event)

    def get_cc_status(self) -> dict:
        """Returns CC status for all 8 personality models."""
        return {name: cc.get_status() for name, cc in self.cc_models.items()}

    # ── Persistence ───────────────────────────────────────────────────────

    async def _save_levels(self, db_conn: asyncpg.Connection) -> None:
        uid = _uuid.UUID(self.user_id)
        for name, tracker in self.xp_trackers.items():
            await db_conn.execute(
                """INSERT INTO model_levels
                       (user_id, model_name, timeframe, context, level, xp, streak, bars_learned, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                   ON CONFLICT (user_id, model_name, timeframe, context)
                   DO UPDATE SET
                       level        = EXCLUDED.level,
                       xp           = EXCLUDED.xp,
                       streak       = EXCLUDED.streak,
                       bars_learned = EXCLUDED.bars_learned,
                       updated_at   = EXCLUDED.updated_at""",
                uid, name, self.timeframe, self.context,
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
                     AND time       = $8
                     AND timeframe  = $9
                     AND is_training = $10""",
                "win" if trade.won else "loss",
                trade.pnl_points,
                trade.pnl_dollars,
                trade.exit_reason,
                trade.bars_held,
                _uuid.UUID(trade.user_id),
                trade.model_name,
                trade.entry_time,
                self.timeframe,
                self.context == "offline",
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

    # ── Model-state persistence ─────────────────────────────────────────────

    async def save_state(self, db_conn: asyncpg.Connection) -> None:
        """
        Persist pickled model objects (8 Champion/Challenger wrappers + Personal)
        so learned River weights survive a backend restart.

        Each model is pickled and upserted independently — a failure on one model
        never blocks the others.  Called periodically from learn_all() and once
        more on graceful shutdown.
        """
        uid = _uuid.UUID(self.user_id)
        items: list[tuple[str, object]] = list(self.cc_models.items()) + [("personal", self.personal)]
        for name, obj in items:
            try:
                blob = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
            except Exception as exc:
                logger.warning("save_state: pickle failed for %s/%s: %s", self.user_id, name, exc)
                continue
            try:
                await db_conn.execute(
                    """INSERT INTO model_state (user_id, model_name, timeframe, context, state, bars_count, updated_at)
                       VALUES ($1, $2, $3, $4, $5, $6, NOW())
                       ON CONFLICT (user_id, model_name, timeframe, context)
                       DO UPDATE SET state      = EXCLUDED.state,
                                     bars_count = EXCLUDED.bars_count,
                                     updated_at = EXCLUDED.updated_at""",
                    uid, name, self.timeframe, self.context, blob, self.bar_count,
                )
            except Exception as exc:
                logger.warning("save_state: DB write failed for %s/%s: %s", self.user_id, name, exc)

    def restore_state(self, saved: dict[str, bytes]) -> int:
        """
        Unpickle saved model objects over the freshly-constructed defaults.
        A blob that fails to unpickle (e.g. after a model class change) is
        skipped, leaving that model at its fresh default rather than crashing.
        Returns the number of models successfully restored.
        """
        restored = 0
        for name, blob in saved.items():
            try:
                obj = pickle.loads(blob)
            except Exception as exc:
                logger.warning(
                    "restore_state: unpickle failed for %s/%s — using fresh model: %s",
                    self.user_id, name, exc,
                )
                continue
            if name == "personal":
                self.personal = obj
                restored += 1
            elif name in self.cc_models:
                self.cc_models[name] = obj
                restored += 1
            else:
                logger.warning("restore_state: unknown model_name %r in saved state — skipped", name)
        return restored

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


# ── Global per-(user, timeframe, context) registry ──────────────────────────

_pipelines: dict[tuple[str, str, str], MLPipeline] = {}
_pipeline_locks: dict[tuple[str, str, str], asyncio.Lock] = {}


async def _load_state_blobs(
    db_conn: asyncpg.Connection, user_id: str, timeframe: str, context: str
) -> dict[str, bytes]:
    """model_state blobs for one (user, timeframe, context), as {model_name: bytes}."""
    rows = await db_conn.fetch(
        "SELECT model_name, state FROM model_state "
        "WHERE user_id = $1 AND timeframe = $2 AND context = $3",
        _uuid.UUID(user_id), timeframe, context,
    )
    return {r["model_name"]: r["state"] for r in rows or []}


async def get_pipeline(
    user_id, db_conn: asyncpg.Connection, timeframe: str = "5min", context: str = "live"
) -> MLPipeline:
    # Canonical key: (str(user_id), timeframe, context). Each (timeframe, context)
    # is a fully independent pipeline with its own persisted weights + levels. The
    # 'offline' context is a COPY of 'live' seeded on first creation and NEVER
    # mutates live thereafter.
    user_id = str(user_id)
    key = (user_id, timeframe, context)

    # Fast path — no lock needed for reads once the pipeline exists
    if key in _pipelines:
        return _pipelines[key]

    # Ensure a per-key lock exists (synchronous, atomic in asyncio — no await
    # between the check and the assignment so no race on lock creation)
    if key not in _pipeline_locks:
        _pipeline_locks[key] = asyncio.Lock()

    async with _pipeline_locks[key]:
        # Re-check inside the lock: another coroutine may have created the
        # pipeline while we were waiting to acquire the lock
        if key in _pipelines:
            return _pipelines[key]

        try:
            rows = await db_conn.fetch(
                """SELECT model_name, level, xp, streak, bars_learned
                   FROM   model_levels
                   WHERE  user_id = $1 AND timeframe = $2 AND context = $3""",
                _uuid.UUID(user_id), timeframe, context,
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
            logger.warning("get_pipeline: could not load model levels for %s/%s/%s (%s) — using defaults", user_id, timeframe, context, exc)
            initial_levels = {}

        pipeline = MLPipeline(user_id, initial_levels, timeframe=timeframe, context=context)

        # Restore persisted River weights so learning survives restarts, scoped to
        # THIS (timeframe, context). Falls back to fresh models on any failure. The
        # 'lstm' row uses a different (PyTorch) format and is loaded separately.
        try:
            saved = await _load_state_blobs(db_conn, user_id, timeframe, context)

            # Offline seed: the first time an offline pipeline is created it has no
            # weights of its own. Deep-copy the CURRENT live weights so it starts
            # exactly where live is, then diverges as it learns from history. To
            # capture live's latest in-memory learning (not just the last periodic
            # save), flush the in-memory live pipeline first, then read its blobs.
            if context == "offline" and not saved:
                live_key = (user_id, timeframe, "live")
                live_pl = _pipelines.get(live_key)
                if live_pl is not None:
                    try:
                        await live_pl.save_state(db_conn)
                    except Exception as exc:
                        logger.warning("get_pipeline: live snapshot before offline seed failed for %s/%s (%s)", user_id, timeframe, exc)
                saved = await _load_state_blobs(db_conn, user_id, timeframe, "live")
                if saved:
                    logger.info(
                        "get_pipeline: seeding offline models for %s/%s from %d live weight blob(s)",
                        user_id, timeframe, len(saved),
                    )

            lstm_blob = saved.pop("lstm", None)

            if saved:
                n = pipeline.restore_state(saved)
                logger.info(
                    "get_pipeline: restored %d/%d River model states for user %s/%s/%s",
                    n, len(saved), user_id, timeframe, context,
                )

            if lstm_blob is not None and pipeline.lstm is not None:
                try:
                    pipeline.lstm.load(lstm_blob)
                    logger.info("get_pipeline: restored trained LSTM for user %s/%s/%s", user_id, timeframe, context)
                except Exception as exc:
                    logger.warning(
                        "get_pipeline: LSTM load failed for %s/%s/%s (%s) — staying untrained",
                        user_id, timeframe, context, exc,
                    )
        except Exception as exc:
            logger.warning(
                "get_pipeline: model_state load failed for %s/%s/%s (%s) — using fresh models",
                user_id, timeframe, context, exc,
            )

        _pipelines[key] = pipeline
        logger.info("ML pipeline created for user %s/%s/%s", user_id, timeframe, context)
        return pipeline
