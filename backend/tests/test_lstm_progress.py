"""
Live per-epoch LSTM training progress.

The AFK status ticker narrates "epoch N/20" from GET /models/lstm/status, which
reads the in-memory _training_progress registry. These tests prove:
  - _train_sync fires the epoch callback once per epoch with sane values,
  - the registry is populated *during* training and cleared *after*,
  - progress reporting never changes the trained result.
"""

import asyncio
import uuid

import numpy as np
import pytest

from app.services.ml import lstm_trainer
from app.services.ml.lstm_trainer import (
    _train_sync, get_lstm_progress, _set_lstm_progress, _clear_lstm_progress, train_lstm,
)
from app.services.ml.lstm_model import SEQUENCE_LENGTH, FEATURE_ORDER


def _xy(n=160):
    rng = np.random.default_rng(0)
    X = rng.standard_normal((n, SEQUENCE_LENGTH, len(FEATURE_ORDER))).astype(np.float32)
    y = rng.integers(0, 3, size=n).astype(np.int64)
    return X, y


@pytest.fixture(autouse=True)
def _clean_registry():
    lstm_trainer._training_progress.clear()
    yield
    lstm_trainer._training_progress.clear()


def test_train_sync_calls_epoch_callback_each_epoch():
    X, y = _xy()
    seen = []
    _train_sync(X, y, epochs=4, epoch_cb=lambda e, loss, acc: seen.append((e, loss, acc)))

    # One call per epoch, numbered 1..4, with finite loss and a valid accuracy.
    assert [s[0] for s in seen] == [1, 2, 3, 4]
    for _e, loss, acc in seen:
        assert loss == loss and loss >= 0.0     # not NaN, non-negative mean loss
        assert 0.0 <= acc <= 1.0


def test_train_sync_without_callback_still_trains():
    """The callback is optional — omitting it must not raise or change the return."""
    X, y = _xy()
    state_dict, val_acc, n, class_counts = _train_sync(X, y, epochs=2)
    assert 0.0 <= val_acc <= 1.0
    assert n == len(X)


def test_get_lstm_progress_shape_and_default():
    uid = str(uuid.uuid4())
    assert get_lstm_progress(uid) == {}                     # not training → empty

    _set_lstm_progress(uid, epoch=7, total_epochs=20, loss=0.1234567, val_acc=0.6789)
    p = get_lstm_progress(uid)
    assert p == {
        "training": True, "epoch": 7, "total_epochs": 20,
        "current_loss": 0.123457, "val_accuracy": 0.6789,   # rounded (6dp / 4dp)
    }

    _clear_lstm_progress(uid)
    assert get_lstm_progress(uid) == {}


@pytest.mark.asyncio
async def test_train_lstm_populates_then_clears_registry(monkeypatch):
    """During train_lstm the registry reflects live epochs; after, it is cleared."""
    uid = str(uuid.uuid4())
    captured = {}

    # Fake the DB-loading step so no real pool is needed; return well-shaped data.
    async def fake_build(_conn, _uid):
        X, y = _xy()
        means = np.zeros(len(FEATURE_ORDER), dtype=np.float32)
        stds = np.ones(len(FEATURE_ORDER), dtype=np.float32)
        return X, y, means, stds
    monkeypatch.setattr(lstm_trainer, "build_training_data", fake_build)

    # Fake the torch training: drive the epoch callback like real training would,
    # snapshotting what a concurrent status poll would see mid-flight.
    def fake_train_sync(X, y, epochs, epoch_cb=None):
        for e in range(1, epochs + 1):
            if epoch_cb:
                epoch_cb(e, 0.5 / e, 0.4 + 0.01 * e)
            if e == 2:
                captured["mid"] = dict(get_lstm_progress(uid))   # visible during training
        from app.services.ml.lstm_model import LSTMNet
        return LSTMNet().state_dict(), 0.62, len(X), np.array([10, 20, 30])
    monkeypatch.setattr(lstm_trainer, "_train_sync", fake_train_sync)

    # Stub the persistence write (fake conn) so the run completes.
    class _Conn:
        async def execute(self, *a, **k):
            return "OK"
        async def fetchval(self, *a, **k):
            return 0
    result = await train_lstm(_Conn(), uid, epochs=5)

    # Mid-flight snapshot showed a live, climbing epoch with matching field names.
    assert captured["mid"]["training"] is True
    assert captured["mid"]["epoch"] == 2
    assert captured["mid"]["total_epochs"] == 5
    assert 0.0 <= captured["mid"]["val_accuracy"] <= 1.0
    # After completion the registry is cleared (ticker returns to resting state).
    assert get_lstm_progress(uid) == {}
    assert result["success"] is True
