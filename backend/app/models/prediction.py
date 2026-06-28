# Pydantic models for ML predictions and the model level system.
# Prediction: per-bar signal from a single model (signal, confidence, targets, actual_outcome).
# ModelLevel: current XP, level, streak, rank, progress to next level, and unlocked settings
#             for one model instance scoped to one user.
# LevelUpEvent: published to Redis pub/sub "live:{user_id}" when a model advances a level;
#               forwarded to the browser via WebSocket to trigger the level-up animation.

from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class Prediction(BaseModel):
    id: UUID
    time: datetime
    user_id: UUID
    model_name: str
    signal: str                     # "BUY" | "SELL" | "HOLD"
    confidence: float | None
    predicted_high: float | None
    predicted_low: float | None
    direction_up_prob: float | None
    actual_outcome: str | None      # filled on next bar close
    created_at: datetime

    class Config:
        from_attributes = True


class ModelLevel(BaseModel):
    user_id: UUID
    model_name: str
    level: int
    xp: int
    streak: int
    bars_learned: int
    rank: str                       # "Rookie" | "Apprentice" | "Pro" | "Elite" | "Expert" | "Master"
    xp_to_next: int                 # XP needed to reach next level (0 if Master)
    xp_progress_pct: float          # 0.0–1.0 progress toward next level
    unlocked_settings: list[str]    # setting names unlocked at current rank

    class Config:
        from_attributes = True


class LevelUpEvent(BaseModel):
    model_name: str
    new_level: int
    new_rank: str
    unlocked: str | None            # name of the newly unlocked setting, or None
