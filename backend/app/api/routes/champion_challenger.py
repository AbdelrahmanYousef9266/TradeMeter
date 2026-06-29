"""
Champion/Challenger API routes.
All endpoints are scoped to the authenticated user's in-memory pipeline.
"""

from fastapi import APIRouter, Depends
from app.core.security import get_current_user
from app.models.user import User
from app.services.ml.pipeline import _pipelines

router = APIRouter()


@router.get("")
async def get_cc_status(user: User = Depends(get_current_user)) -> dict:
    """CC status for all 8 personality models (champion + challenger stats)."""
    pipeline = _pipelines.get(str(user.id))
    if not pipeline:
        return {}
    return pipeline.get_cc_status()


@router.get("/{model_name}")
async def get_model_cc_status(
    model_name: str,
    user: User = Depends(get_current_user),
) -> dict:
    """CC status for a single model."""
    pipeline = _pipelines.get(str(user.id))
    if not pipeline or model_name not in pipeline.cc_models:
        return {}
    return pipeline.cc_models[model_name].get_status()


@router.post("/{model_name}/evaluate")
async def force_evaluation(
    model_name: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Force an immediate Champion/Challenger evaluation for this model."""
    pipeline = _pipelines.get(str(user.id))
    if not pipeline or model_name not in pipeline.cc_models:
        return {"error": "Model not found or pipeline not loaded"}

    cc = pipeline.cc_models[model_name]
    cc.bars_since_eval = cc.eval_interval   # trigger evaluation
    promotion = cc.maybe_evaluate()

    if promotion:
        return {
            "promoted":       True,
            "winner":         promotion.winner,
            "champion_pnl":   round(promotion.champion_pnl, 2),
            "challenger_pnl": round(promotion.challenger_pnl, 2),
            "new_params":     promotion.new_params,
            "old_params":     promotion.old_params,
        }

    return {"promoted": False, "message": "Champion retained — challenger reset with new mutations"}
