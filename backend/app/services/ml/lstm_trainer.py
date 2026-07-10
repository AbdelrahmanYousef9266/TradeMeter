"""
LSTM training pipeline — offline batch training on TimescaleDB history.

Triggered by:
1. Nightly scheduled job (asyncio task in main.py)
2. Manual button on dashboard (POST /models/lstm/train)

Persists the trained network into the shared `model_state` table (the same
table used by the Tier-1 persistence layer), keyed by (user_id, 'lstm').
"""

import asyncio
import logging
import uuid as _uuid
from datetime import datetime, timezone

import numpy as np
import torch
import torch.nn as nn

from app.services.ml.lstm_model import (
    LSTMNet, LSTMModel, SEQUENCE_LENGTH,
    MIN_BARS_TO_ACTIVATE, FEATURE_ORDER,
)
from app.services.market_data.features import FeatureEngine

logger = logging.getLogger(__name__)

# The LSTM is the 5-min model (Phase 2) — the primary trading timeframe. Its data
# gate, training set, and persisted state all live under this timeframe.
LSTM_TIMEFRAME = "5min"


# ── Live training-progress registry (per user) ───────────────────────────────
#
# LSTM training runs off the event loop in asyncio.to_thread, so there is no
# natural place to observe mid-flight progress. This in-memory dict, keyed by
# str(user_id) like the other per-user registries, holds a live snapshot updated
# at the end of each epoch. GET /models/lstm/status reads it so the frontend can
# narrate "epoch N/20" in real time. Empty (absent) means "not training".
#
# Field names are chosen to match what the AFK status ticker reads directly:
# `training` (bool), `epoch`, `total_epochs`, `val_accuracy` (plus `current_loss`
# for the Live Activity Panel). The per-epoch callback runs in the training
# thread; a whole-dict reassignment is atomic in CPython, so the status reader
# never sees a torn partial update.
_training_progress: dict[str, dict] = {}


def get_lstm_progress(user_id) -> dict:
    """Live training snapshot for a user, or {} when not currently training."""
    return _training_progress.get(str(user_id), {})


def _set_lstm_progress(user_id, *, epoch, total_epochs, loss, val_acc) -> None:
    _training_progress[str(user_id)] = {
        "training":     True,
        "epoch":        epoch,
        "total_epochs": total_epochs,
        "current_loss": None if loss is None else round(float(loss), 6),
        "val_accuracy": None if val_acc is None else round(float(val_acc), 4),
    }


def _clear_lstm_progress(user_id) -> None:
    _training_progress.pop(str(user_id), None)


def _as_uuid(user_id) -> _uuid.UUID:
    """asyncpg requires a uuid.UUID for UUID columns — accept str or UUID."""
    return user_id if isinstance(user_id, _uuid.UUID) else _uuid.UUID(str(user_id))


def label_from_move(move: float, atr: float) -> int:
    """
    Classify a one-bar forward price move into SELL(0) / HOLD(1) / BUY(2).
      BUY  if move >  0.5 * ATR
      SELL if move < -0.5 * ATR
      HOLD otherwise
    """
    if move > 0.5 * atr:
        return 2   # BUY
    if move < -0.5 * atr:
        return 0   # SELL
    return 1       # HOLD


async def count_available_bars(db_conn, user_id) -> int:
    """
    How many DISTINCT-timestamp bar closes does this user have?

    Counts distinct timestamps, not raw rows: replaying the same historical
    session in training mode inserts duplicate-timestamp bars, and counting the
    copies would falsely inflate the LSTM activation gate (MIN_BARS_TO_ACTIVATE).
    Training-tagged bars still count — replayed history is legitimate data — but
    each timestamp counts once.
    """
    # Scoped to the 5-min series (Phase 2): the LSTM is the 5-min model — the
    # primary trading timeframe. Only 5-min bars count toward its activation gate.
    row = await db_conn.fetchrow(
        "SELECT COUNT(DISTINCT time) AS n FROM ticks "
        "WHERE user_id = $1 AND bar_type != 'tick' AND timeframe = $2",
        _as_uuid(user_id), LSTM_TIMEFRAME,
    )
    return row["n"] if row else 0


async def build_training_data(db_conn, user_id):
    """
    Load all bars from TimescaleDB, recompute features in order,
    build (sequence, label) pairs for training.

    Returns (X, y, means, stds) or None if insufficient data.

    Label logic: for each sequence ending at bar t, the label is:
      BUY  (2) if close[t+1] > close[t] by more than 0.5 * ATR
      SELL (0) if close[t+1] < close[t] by more than 0.5 * ATR
      HOLD (1) otherwise
    """
    # Deduplicate by timestamp so a session replayed multiple times in training
    # mode can't feed the LSTM duplicate sequences (which would bias it toward
    # whichever session was replayed most) or double-count toward the data gate.
    # DISTINCT ON (time) keeps exactly one row per timestamp; ORDER BY time ASC,
    # is_training ASC makes it prefer the live row over a training copy when both
    # exist. Training-tagged bars are still included — the fix is dedup, not
    # exclusion. The result is strictly increasing in time with no duplicates.
    # 5-min series only (see count_available_bars): the LSTM is the 5-min model
    # in Phase 2, so only 5-min bars enter its training set.
    rows = await db_conn.fetch(
        """SELECT DISTINCT ON (time) time, open, high, low, close, volume, bar_type
           FROM ticks
           WHERE user_id = $1 AND bar_type != 'tick' AND timeframe = $2
           ORDER BY time ASC, is_training ASC""",
        _as_uuid(user_id), LSTM_TIMEFRAME,
    )

    if len(rows) < MIN_BARS_TO_ACTIVATE:
        return None

    # Recompute features in chronological order using the same engine as live
    engine = FeatureEngine()
    feature_rows = []
    closes = []
    atrs = []

    class _Bar:
        __slots__ = ("time", "open", "high", "low", "close", "volume")

        def __init__(self, r):
            self.time = r["time"]
            self.open = r["open"]
            self.high = r["high"]
            self.low = r["low"]
            self.close = r["close"]
            self.volume = r["volume"]

    for r in rows:
        feats = engine.update(_Bar(r))
        if feats is not None:
            vec = [feats.get(k, 0.0) for k in FEATURE_ORDER]
            feature_rows.append(vec)
            closes.append(r["close"])
            atrs.append(feats.get("atr_14", 1.0))

    if len(feature_rows) < SEQUENCE_LENGTH + 100:
        return None

    feature_arr = np.array(feature_rows, dtype=np.float32)

    # Normalization stats
    means = feature_arr.mean(axis=0)
    stds = feature_arr.std(axis=0) + 1e-8

    # Build sequences and labels.
    #
    # Alignment must match live inference: at serving time the window ends at the
    # just-closed bar and the model predicts the move of the VERY NEXT bar. So for
    # a sequence covering [i, i+SEQUENCE_LENGTH-1] the label is the move from the
    # last sequence bar to the one immediately after it — using the ATR known at
    # that last bar. (The previous code labelled one bar too far out, a train/serve
    # mismatch that degraded accuracy.)
    X, y = [], []
    for i in range(len(feature_arr) - SEQUENCE_LENGTH):
        seq = feature_arr[i: i + SEQUENCE_LENGTH]
        seq_norm = (seq - means) / stds

        last = i + SEQUENCE_LENGTH - 1        # index of the last bar in the sequence
        move = closes[last + 1] - closes[last]
        label = label_from_move(move, atrs[last])

        X.append(seq_norm)
        y.append(label)

    return (
        np.array(X, dtype=np.float32),
        np.array(y, dtype=np.int64),
        means,
        stds,
    )


def _train_sync(X, y, epochs: int, epoch_cb=None):
    """
    Pure synchronous PyTorch training — runs in a worker thread so it does
    NOT block the asyncio event loop.

    Captures nothing async; all torch tensors/ops live entirely inside here.
    If `epoch_cb` is given it is called at the end of each epoch with
    (epoch_number, mean_epoch_loss, val_acc) for live progress reporting — a
    cheap extra val forward-pass per epoch, no effect on the trained result.
    Returns (state_dict, val_acc, train_samples, class_counts).
    """
    # Train/validation split (80/20, chronological — no shuffle across the split)
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    X_train_t = torch.tensor(X_train)
    y_train_t = torch.tensor(y_train)
    X_val_t = torch.tensor(X_val)
    y_val_t = torch.tensor(y_val)

    net = LSTMNet()
    net.train()

    # Weighted loss to handle class imbalance (HOLD is usually most common)
    class_counts = np.bincount(y_train, minlength=3)
    weights = torch.tensor(
        [len(y_train) / (3 * max(c, 1)) for c in class_counts],
        dtype=torch.float32,
    )
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.Adam(net.parameters(), lr=0.001)

    batch_size = 64
    n_batches = max(1, len(X_train) // batch_size)

    for _epoch in range(epochs):
        net.train()
        perm = torch.randperm(len(X_train_t))
        epoch_loss = 0.0
        for b in range(n_batches):
            idx = perm[b * batch_size: (b + 1) * batch_size]
            xb, yb = X_train_t[idx], y_train_t[idx]

            optimizer.zero_grad()
            out = net(xb)
            loss = criterion(out, yb)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        # Live per-epoch progress (val forward-pass is cheap; keeps the ticker honest).
        if epoch_cb is not None:
            net.eval()
            with torch.no_grad():
                if len(X_val_t) > 0:
                    ep_pred = torch.argmax(net(X_val_t), dim=1)
                    ep_val_acc = (ep_pred == y_val_t).float().mean().item()
                else:
                    ep_val_acc = 0.0
            try:
                epoch_cb(_epoch + 1, epoch_loss / n_batches, ep_val_acc)
            except Exception:
                pass   # progress reporting must never break training

    # Validation accuracy
    net.eval()
    with torch.no_grad():
        if len(X_val_t) > 0:
            val_out = net(X_val_t)
            val_pred = torch.argmax(val_out, dim=1)
            val_acc = (val_pred == y_val_t).float().mean().item()
        else:
            val_acc = 0.0

    return net.state_dict(), val_acc, len(X), class_counts


async def train_lstm(db_conn, user_id, epochs: int = 20,
                     progress_callback=None) -> dict:
    """
    Train the LSTM on the user's full history and persist it.

    DB work (loading bars, saving the blob) stays on the event loop; the
    blocking PyTorch training runs in asyncio.to_thread so the WebSocket feed
    and ingestion keep flowing during the ~minute of training.

    `progress_callback` is accepted for API compatibility. Live per-epoch
    progress is published to the in-memory `_training_progress` registry (read by
    GET /models/lstm/status) rather than called back onto the event loop, since
    the torch work runs off-loop in a thread.

    Returns a training results dict.
    """
    # ── Async: load data from DB ──────────────────────────────────────────
    data = await build_training_data(db_conn, user_id)
    if data is None:
        bars = await count_available_bars(db_conn, user_id)
        return {
            "success": False,
            "reason": "insufficient_data",
            "bars_available": bars,
            "bars_needed": MIN_BARS_TO_ACTIVATE,
        }

    X, y, means, stds = data

    # The epoch callback runs inside the worker thread; a whole-dict reassignment
    # in _set_lstm_progress is atomic in CPython, so the status reader is safe.
    def _epoch_cb(epoch, loss, val_acc):
        _set_lstm_progress(user_id, epoch=epoch, total_epochs=epochs,
                           loss=loss, val_acc=val_acc)

    # Seed the registry immediately so a status poll right after the button click
    # already shows "training, epoch 0/N" before the first epoch completes.
    _set_lstm_progress(user_id, epoch=0, total_epochs=epochs, loss=None, val_acc=None)

    # ── Off-loop: run the blocking torch training in a worker thread ──────
    try:
        state_dict, val_acc, n_samples, class_counts = await asyncio.to_thread(
            _train_sync, X, y, epochs, _epoch_cb,
        )
    finally:
        # Always clear progress — success, failure, or cancellation — so the
        # ticker returns to its resting state and never shows a stale "training".
        _clear_lstm_progress(user_id)

    # ── Async: rebuild model from trained weights, serialize, persist ─────
    model = LSTMModel(str(user_id))
    model.net.load_state_dict(state_dict)
    model.net.eval()
    model.is_trained = True
    model.feature_means = means
    model.feature_stds = stds
    model.last_trained = datetime.now(timezone.utc)
    model.train_samples = n_samples
    model.train_accuracy = val_acc

    # Persist into the shared model_state table under the 5-min timeframe (the
    # LSTM's series), keyed by (user_id, 'lstm', '5min').
    await db_conn.execute(
        """INSERT INTO model_state (user_id, model_name, timeframe, state, bars_count, updated_at)
           VALUES ($1, 'lstm', $2, $3, $4, NOW())
           ON CONFLICT (user_id, model_name, timeframe)
           DO UPDATE SET state      = EXCLUDED.state,
                         bars_count = EXCLUDED.bars_count,
                         updated_at = NOW()""",
        _as_uuid(user_id), LSTM_TIMEFRAME, model.serialize(), n_samples,
    )

    logger.info(
        "LSTM trained for user %s: %d samples, val_acc=%.4f",
        user_id, len(X), val_acc,
    )

    return {
        "success": True,
        "train_samples": len(X),
        "val_accuracy": round(val_acc, 4),
        "epochs": epochs,
        "class_distribution": {
            "SELL": int(class_counts[0]),
            "HOLD": int(class_counts[1]),
            "BUY":  int(class_counts[2]),
        },
    }
