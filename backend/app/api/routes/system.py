"""
System resource stats for the AI Lab stream panel.

  GET /system/stats → { cpu_percent, ram_used_gb, ram_total_gb, ram_percent }

Real host metrics via psutil. Polled ~every 2s by the AI-Lab / AFK page, so it is
deliberately cheap: psutil.cpu_percent(interval=None) is non-blocking (it returns
usage since the previous call rather than sleeping). If psutil is unavailable the
endpoint returns zeros so the page never breaks.

GPU is NOT reported here — this is a CPU-only system; the AI Lab renders a clearly
decorative GPU gauge on the frontend instead.
"""

import logging

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()

try:
    import psutil
    _HAVE_PSUTIL = True
except Exception:                       # pragma: no cover - psutil optional
    _HAVE_PSUTIL = False

_ZEROS = {"cpu_percent": 0.0, "ram_used_gb": 0.0, "ram_total_gb": 0.0, "ram_percent": 0.0}
_GB = 1024 ** 3


@router.get("/stats")
async def system_stats(user: User = Depends(get_current_user)) -> dict:
    """Real CPU + RAM usage of the backend host (cheap, non-blocking)."""
    if not _HAVE_PSUTIL:
        return dict(_ZEROS)
    try:
        cpu = psutil.cpu_percent(interval=None)   # non-blocking: usage since last call
        vm  = psutil.virtual_memory()
        return {
            "cpu_percent":  round(cpu, 1),
            "ram_used_gb":  round(vm.used / _GB, 2),
            "ram_total_gb": round(vm.total / _GB, 2),
            "ram_percent":  round(vm.percent, 1),
        }
    except Exception as exc:            # pragma: no cover - defensive
        logger.warning("system_stats failed: %s", exc)
        return dict(_ZEROS)
