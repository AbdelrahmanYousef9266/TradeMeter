"""
/market/data-integrity — health check over stored bars: complete vs partial
days, duplicate-timestamp count, and weekday gap detection.
"""

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.api.routes.market import data_integrity


USER = SimpleNamespace(id=uuid.uuid4())


class IntegrityConn:
    def __init__(self, day_rows, dup):
        self._days = day_rows
        self._dup = dup

    async def fetch(self, q, *a):
        return self._days

    async def fetchval(self, q, *a):
        return self._dup


def _expected_missing(day_rows):
    present = {r["day"] for r in day_rows}
    lo, hi = day_rows[0]["day"], day_rows[-1]["day"]
    out, cur = [], lo
    while cur <= hi:
        if cur.weekday() < 5 and cur not in present:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


@pytest.mark.asyncio
async def test_integrity_aggregation_and_gaps():
    # A week with two present days bracketing a mid-week gap and a weekend.
    days = [
        {"day": date(2026, 6, 1), "bars": 390},   # complete
        {"day": date(2026, 6, 2), "bars": 200},   # partial
        # 06-03, 06-04 weekdays missing (gap)
        {"day": date(2026, 6, 5), "bars": 400},   # complete
        # 06-06, 06-07 weekend (must NOT count as missing)
        {"day": date(2026, 6, 8), "bars": 380},   # complete
    ]
    out = await data_integrity(user=USER, conn=IntegrityConn(days, dup=0))

    assert out["total_days"] == 4
    assert out["complete_days"] == 3            # 390, 400, 380
    assert out["partial_days"] == 1             # 200
    assert out["duplicate_timestamps"] == 0
    assert out["date_range"] == {"min": "2026-06-01", "max": "2026-06-08"}

    exp = _expected_missing(days)
    assert out["missing_weekdays"]["count"] == len(exp)
    assert out["missing_weekdays"]["dates"] == exp
    # The weekend (06-06/06-07) is excluded; the mid-week gap is included.
    assert "2026-06-03" in exp and "2026-06-04" in exp
    assert "2026-06-06" not in exp and "2026-06-07" not in exp


@pytest.mark.asyncio
async def test_integrity_reports_duplicates():
    days = [{"day": date(2026, 6, 1), "bars": 400}]
    out = await data_integrity(user=USER, conn=IntegrityConn(days, dup=17))
    assert out["duplicate_timestamps"] == 17


@pytest.mark.asyncio
async def test_integrity_empty():
    out = await data_integrity(user=USER, conn=IntegrityConn([], dup=0))
    assert out["total_days"] == 0
    assert out["missing_weekdays"] == {"count": 0, "dates": []}
    assert out["date_range"] == {"min": None, "max": None}
