"""
Blend weight computation for personal models (Models 9 and 10).

Weights are derived from rolling 50-bar accuracy, then rank multipliers
are applied (Elite 1.5×, Expert 1.75×, Master 2×), then normalized to sum to 1.
Manual override weights bypass accuracy-based computation.
"""

from collections import deque
from app.services.ml.xp import rank_to_multiplier


_MODEL_NAMES = [
    "scalper", "momentum", "mean_reversion", "breakout",
    "conservative", "aggressive", "volume", "contrarian",
]


def compute_blend_weights(
    rolling_accuracy: dict[str, deque],
    level_ranks:      dict[str, str],
    manual_weights:   dict[str, float] | None,
) -> dict[str, float]:
    """
    Return normalized blend weights for the 8 personality models.

    Steps:
    1. If manual_weights supplied → normalize and return them.
    2. Compute mean accuracy per model (default 0.5 if deque is empty).
    3. Apply rank multiplier from xp.rank_to_multiplier().
    4. Normalize so all weights sum to 1.0.
    """
    names = _MODEL_NAMES

    if manual_weights:
        total = sum(manual_weights.values())
        if total > 0:
            return {k: manual_weights.get(k, 0.0) / total for k in names}

    weights: dict[str, float] = {}
    for name in names:
        acc_deque = rolling_accuracy.get(name, deque())
        mean_acc  = sum(acc_deque) / len(acc_deque) if acc_deque else 0.5
        rank      = level_ranks.get(name, "Rookie")
        weights[name] = mean_acc * rank_to_multiplier(rank)

    total = sum(weights.values())
    if total <= 0:
        n = len(names)
        return {k: 1.0 / n for k in names}

    return {k: v / total for k, v in weights.items()}
