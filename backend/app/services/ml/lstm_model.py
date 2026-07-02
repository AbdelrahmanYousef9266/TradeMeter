"""
PyTorch LSTM model — Model 11.

Learns multi-bar sequence patterns that the River models can't capture.
Trains in batch on TimescaleDB history. Predicts live via inference.

Stays dormant (no predictions) until MIN_BARS_TO_ACTIVATE bars exist.

Unlike the River models this does NOT learn per bar — it has two separate
code paths: a training path (offline, see lstm_trainer.py) and an inference
path (live, the predict() method here).
"""

import pickle
from collections import deque

import numpy as np
import torch
import torch.nn as nn

SEQUENCE_LENGTH = 50          # bars per sequence
N_FEATURES = 16               # our 16 features
MIN_BARS_TO_ACTIVATE = 2000   # dormant until this many bars exist
HIDDEN_SIZE = 64
NUM_LAYERS = 2

FEATURE_ORDER = [
    "rsi_14", "ema_9", "ema_21", "ema_50", "macd", "macd_signal",
    "atr_14", "volume_delta", "bar_range", "close_position",
    "vwap", "vwap_distance", "vwap_cross",
    "session_minutes", "session_phase", "is_power_hour",
]


class LSTMNet(nn.Module):
    """LSTM network: 50-bar sequence of 16 features → SELL/HOLD/BUY."""

    def __init__(self, n_features=N_FEATURES, hidden=HIDDEN_SIZE, layers=NUM_LAYERS):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden,
            num_layers=layers,
            batch_first=True,
            dropout=0.2 if layers > 1 else 0.0,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, 3),  # 3 classes: SELL=0, HOLD=1, BUY=2
        )

    def forward(self, x):
        # x: (batch, seq_len, n_features)
        out, _ = self.lstm(x)
        last = out[:, -1, :]   # use final timestep
        return self.fc(last)


class LSTMModel:
    """
    Wrapper for the LSTM that fits TradeMeter's model interface.
    Per-user instance (scoped by user_id).
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.name = "lstm"
        self.net = LSTMNet()
        self.net.eval()  # start in inference mode
        self.is_trained = False
        self.feature_means = np.zeros(N_FEATURES, dtype=np.float32)
        self.feature_stds = np.ones(N_FEATURES, dtype=np.float32)

        # Rolling window of recent feature vectors for live inference
        self.feature_window: deque = deque(maxlen=SEQUENCE_LENGTH)

        # Training metadata
        self.last_trained = None
        self.train_samples = 0
        self.train_accuracy = 0.0

    def add_features(self, features: dict):
        """Add latest bar's features to the rolling window (for live inference)."""
        vec = np.array([features.get(k, 0.0) for k in FEATURE_ORDER], dtype=np.float32)
        self.feature_window.append(vec)

    def can_predict(self) -> bool:
        """Returns True only if trained AND window is full."""
        return self.is_trained and len(self.feature_window) == SEQUENCE_LENGTH

    def predict(self, features: dict, last_close: float):
        """
        Live inference. Returns a ModelPrediction-compatible object.
        If not trained or window not full, returns HOLD.

        Feeds the rolling window on EVERY call (even when dormant) so the moment
        the model is trained it already has a full 50-bar window ready.
        """
        from app.services.ml.models.base import ModelPrediction

        self.add_features(features)

        if not self.can_predict():
            return ModelPrediction(
                signal="HOLD", confidence=0.0,
                direction_up=0.5, direction_down=0.5,
                predicted_high=last_close, predicted_low=last_close,
            )

        # Build input tensor from window
        seq = np.array(self.feature_window, dtype=np.float32)
        # Normalize using training stats
        seq = (seq - self.feature_means) / (self.feature_stds + 1e-8)
        x = torch.tensor(seq, dtype=torch.float32).unsqueeze(0)  # (1, 50, 16)

        with torch.no_grad():
            logits = self.net(x)
            probs = torch.softmax(logits, dim=1).numpy()[0]

        # probs: [SELL, HOLD, BUY]
        sell_p, hold_p, buy_p = probs[0], probs[1], probs[2]
        max_idx = int(np.argmax(probs))
        signal = ["SELL", "HOLD", "BUY"][max_idx]
        confidence = float(probs[max_idx])

        atr = features.get("atr_14", 1.0)
        return ModelPrediction(
            signal=signal,
            confidence=confidence,
            direction_up=float(buy_p),
            direction_down=float(sell_p),
            predicted_high=last_close + atr * 2,
            predicted_low=last_close - atr * 2,
        )

    def serialize(self) -> bytes:
        """Serialize model state for DB storage."""
        return pickle.dumps({
            "state_dict": self.net.state_dict(),
            "is_trained": self.is_trained,
            "feature_means": self.feature_means,
            "feature_stds": self.feature_stds,
            "last_trained": self.last_trained,
            "train_samples": self.train_samples,
            "train_accuracy": self.train_accuracy,
        })

    def load(self, data: bytes):
        """Restore model state from DB."""
        state = pickle.loads(data)
        self.net.load_state_dict(state["state_dict"])
        self.net.eval()
        self.is_trained = state["is_trained"]
        self.feature_means = state["feature_means"]
        self.feature_stds = state["feature_stds"]
        self.last_trained = state["last_trained"]
        self.train_samples = state["train_samples"]
        self.train_accuracy = state["train_accuracy"]
