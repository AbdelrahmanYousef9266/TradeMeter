"""
ADWIN drift detector — one instance per (user_id, model_name) pair.

Triggers when rolling 20-bar accuracy falls below threshold OR when ADWIN
detects a statistically significant change point.  On trigger:
  - caller must reset River model weights
  - caller must reset XP streak (level is preserved)
  - ADWIN itself is reset so it can detect the next regime change
"""

from collections import deque
from river import drift as river_drift


class DriftDetector:

    def __init__(
        self,
        user_id:    str,
        model_name: str,
        threshold:  float = 0.60,
    ) -> None:
        self.user_id    = user_id
        self.model_name = model_name
        self.threshold  = threshold
        self.adwin      = river_drift.ADWIN()
        self.rolling_accuracy: deque[int] = deque(maxlen=50)

    def update(self, correct: bool) -> bool:
        """
        Feed one bar's prediction result.
        Returns True if drift is detected (caller should reset model + streak).
        """
        val = 1 if correct else 0
        self.rolling_accuracy.append(val)
        self.adwin.update(val)

        if len(self.rolling_accuracy) >= 20:
            avg = sum(self.rolling_accuracy) / len(self.rolling_accuracy)
            if avg < self.threshold or self.adwin.drift_detected:
                self.adwin = river_drift.ADWIN()  # reset for next detection window
                return True

        return False

    def reset(self) -> None:
        """Hard reset — used when model weights are externally reset."""
        self.adwin            = river_drift.ADWIN()
        self.rolling_accuracy = deque(maxlen=50)
