"""
XP and level system — pure logic, no I/O, no async.

One XPTracker instance per (user_id, model_name) pair.
Loaded from the model_levels table at pipeline startup, persisted after every bar.
"""

from dataclasses import dataclass
from typing import Optional


# ── XP constants ──────────────────────────────────────────────────────────────

XP_BAR_LEARNED        = 1
XP_CORRECT_DIRECTION  = 10
XP_PNL_IMPROVEMENT    = 5
XP_STREAK_BONUS       = 3   # multiplied by streak count before awarding
XP_WRONG_PREDICTION   = -3


# ── Level / rank helpers ───────────────────────────────────────────────────────

def xp_for_level(level: int) -> int:
    """XP required to advance from `level` to `level + 1`.  Returns 0 at Master."""
    if level >= 100: return 0
    if level >= 80:  return 1200
    if level >= 50:  return 800
    if level >= 20:  return 500
    return 300


def level_to_rank(level: int) -> str:
    if level >= 100: return "Master"
    if level >= 80:  return "Expert"
    if level >= 60:  return "Elite"
    if level >= 40:  return "Pro"
    if level >= 20:  return "Apprentice"
    return "Rookie"


def get_unlocked_settings(rank: str) -> list[str]:
    """Return the cumulative list of setting names unlocked at this rank."""
    unlocks = ["Base settings"]
    if rank in ("Apprentice", "Pro", "Elite", "Expert", "Master"):
        unlocks.append("Confidence threshold")
    if rank in ("Pro", "Elite", "Expert", "Master"):
        unlocks.append("Signal mode presets")
    if rank in ("Elite", "Expert", "Master"):
        unlocks.append("Blend weight boost")
    if rank in ("Expert", "Master"):
        unlocks.append("Aggressive settings")
    if rank == "Master":
        unlocks.append("All settings unlocked")
    return unlocks


def rank_to_multiplier(rank: str) -> float:
    """Blend weight multiplier for the personal model ensemble."""
    return {
        "Rookie":     1.0,
        "Apprentice": 1.0,
        "Pro":        1.0,
        "Elite":      1.5,
        "Expert":     1.75,
        "Master":     2.0,
    }.get(rank, 1.0)


# ── LevelUpEvent ──────────────────────────────────────────────────────────────

@dataclass
class LevelUpEvent:
    model_name: str
    new_level:  int
    new_rank:   str
    unlocked:   Optional[str]   # name of newly unlocked setting, or None


# ── XPTracker ─────────────────────────────────────────────────────────────────

class XPTracker:
    """
    Stateful XP / level tracker for one (user_id, model_name) pair.

    `xp` tracks XP accumulated *within the current level*.
    On level-up any surplus XP carries over so rapid-fire gains don't waste XP.
    """

    def __init__(
        self,
        user_id:      str,
        model_name:   str,
        level:        int = 1,
        xp:           int = 0,
        streak:       int = 0,
        bars_learned: int = 0,
        **_extra,               # ignore extra kwargs from DB row dicts
    ):
        self.user_id      = user_id
        self.model_name   = model_name
        self.level        = max(1, min(level, 100))
        self.xp           = max(0, xp)
        self.streak       = max(0, streak)
        self.bars_learned = max(0, bars_learned)

    # ── Core award logic ──────────────────────────────────────────────────

    def award(
        self,
        direction_up:    float,   # model's predicted probability of up move
        actual_direction: int,    # 1 = bar closed up, 0 = bar closed down
        prev_pnl:        float,
        curr_pnl:        float,
    ) -> Optional[LevelUpEvent]:
        """
        Award XP for one completed bar.  Returns LevelUpEvent if the model
        leveled up, else None.

        Call order: first award(), then persist.
        """
        correct = (direction_up > 0.5) == bool(actual_direction)

        delta = XP_BAR_LEARNED

        if correct:
            delta += XP_CORRECT_DIRECTION
            delta += XP_STREAK_BONUS * self.streak  # bonus before incrementing
            self.streak += 1
        else:
            delta += XP_WRONG_PREDICTION
            self.streak = 0

        if curr_pnl > prev_pnl:
            delta += XP_PNL_IMPROVEMENT

        self.xp = max(0, self.xp + delta)
        self.bars_learned += 1

        return self._check_level_up()

    # ── Level-up check ────────────────────────────────────────────────────

    def _check_level_up(self) -> Optional[LevelUpEvent]:
        if self.level >= 100:
            return None

        old_rank = level_to_rank(self.level)
        leveled_up = False
        event: Optional[LevelUpEvent] = None

        while self.level < 100:
            threshold = xp_for_level(self.level)
            if self.xp < threshold:
                break
            self.xp -= threshold
            self.level += 1
            leveled_up = True

            new_rank = level_to_rank(self.level)
            if new_rank != old_rank:
                # Find the first newly-unlocked setting at the new rank
                old_unlocks = get_unlocked_settings(old_rank)
                new_unlocks = get_unlocked_settings(new_rank)
                newly_unlocked = next(
                    (s for s in new_unlocks if s not in old_unlocks), None
                )
                event = LevelUpEvent(
                    model_name=self.model_name,
                    new_level=self.level,
                    new_rank=new_rank,
                    unlocked=newly_unlocked,
                )
                old_rank = new_rank

        if leveled_up and event is None:
            # Level-up within the same rank — still notify
            event = LevelUpEvent(
                model_name=self.model_name,
                new_level=self.level,
                new_rank=level_to_rank(self.level),
                unlocked=None,
            )

        return event

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        rank      = level_to_rank(self.level)
        threshold = xp_for_level(self.level)
        return {
            "level":            self.level,
            "xp":               self.xp,
            "streak":           self.streak,
            "bars_learned":     self.bars_learned,
            "rank":             rank,
            "xp_to_next":       max(0, threshold - self.xp),
            "xp_progress_pct":  round(self.xp / threshold, 3) if threshold > 0 else 1.0,
            "unlocked_settings": get_unlocked_settings(rank),
        }
