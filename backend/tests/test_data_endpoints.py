"""
Data-inventory endpoints (Data page): /market/data-summary and /market/data-days.

Additive, read-only reporting over ALL bar data (live + training). These tests
lock the response shape, the live/training split, the "complete day" threshold
(>= 370 bars), the live/training/mixed day classification, and month validation.
"""

import uuid
from datetime import datetime, date, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes.market import data_summary, data_days


USER = SimpleNamespace(id=uuid.uuid4())


class SummaryConn:
    def __init__(self, totals, months, symbol):
        self._totals, self._months, self._symbol = totals, months, symbol

    async def fetchrow(self, q, *a):
        if "MIN(time)" in q:
            return self._totals
        if "GROUP BY symbol" in q:
            return self._symbol
        raise AssertionError(f"unexpected fetchrow: {q}")

    async def fetch(self, q, *a):
        assert "date_trunc('month'" in q
        return self._months


@pytest.mark.asyncio
async def test_data_summary_maps_totals_months_and_storage():
    totals = {
        "total_bars": 12000, "total_raw_rows": 21000,
        "live_bars": 5000, "training_bars": 8000,
        "min_time": datetime(2026, 1, 12, tzinfo=timezone.utc),
        "max_time": datetime(2026, 7, 3, tzinfo=timezone.utc),
    }
    months = [
        {"month": "2026-06", "bars": 9074, "days": 22, "live_bars": 0, "training_bars": 9074},
        {"month": "2026-07", "bars": 1110, "days": 3, "live_bars": 500, "training_bars": 610},
    ]
    conn = SummaryConn(totals, months, {"symbol": "MES 09-26"})

    out = await data_summary(user=USER, conn=conn)

    assert out["total_bars"] == 12000
    assert out["total_raw_rows"] == 21000
    assert out["live_bars"] == 5000 and out["training_bars"] == 8000
    assert out["date_range"]["min"].startswith("2026-01-12")
    assert out["instrument"] == "MES 09-26"
    assert out["complete_day_threshold"] == 370
    # storage ≈ raw_rows × 100 bytes → MB
    assert out["storage_estimate_mb"] == round(21000 * 100 / (1024 * 1024), 2)
    assert [m["month"] for m in out["months"]] == ["2026-06", "2026-07"]


@pytest.mark.asyncio
async def test_data_summary_empty_when_no_rows():
    totals = {"total_bars": 0, "total_raw_rows": 0, "live_bars": 0,
              "training_bars": 0, "min_time": None, "max_time": None}
    conn = SummaryConn(totals, [], None)

    out = await data_summary(user=USER, conn=conn)

    assert out["total_raw_rows"] == 0
    assert out["months"] == []
    assert out["date_range"] == {"min": None, "max": None}
    assert out["instrument"] is None


class DaysConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, q, *a):
        assert "date_trunc('day'" in q
        return self._rows


@pytest.mark.asyncio
async def test_data_days_completeness_and_kind():
    rows = [
        {"day": date(2026, 7, 1), "bars": 400, "first_bar": datetime(2026, 7, 1, 13, 31, tzinfo=timezone.utc),
         "last_bar": datetime(2026, 7, 1, 21, 0, tzinfo=timezone.utc), "has_live": True,  "has_training": False},
        {"day": date(2026, 7, 2), "bars": 200, "first_bar": datetime(2026, 7, 2, 13, 31, tzinfo=timezone.utc),
         "last_bar": datetime(2026, 7, 2, 17, 0, tzinfo=timezone.utc), "has_live": False, "has_training": True},
        {"day": date(2026, 7, 3), "bars": 380, "first_bar": datetime(2026, 7, 3, 13, 31, tzinfo=timezone.utc),
         "last_bar": datetime(2026, 7, 3, 20, 0, tzinfo=timezone.utc), "has_live": True,  "has_training": True},
    ]
    out = await data_days(month="2026-07", user=USER, conn=DaysConn(rows))

    d = {x["date"]: x for x in out["days"]}
    assert d["2026-07-01"]["is_complete"] is True  and d["2026-07-01"]["kind"] == "live"
    assert d["2026-07-02"]["is_complete"] is False and d["2026-07-02"]["kind"] == "training"
    assert d["2026-07-03"]["is_complete"] is True  and d["2026-07-03"]["kind"] == "mixed"
    assert d["2026-07-01"]["first_bar"].endswith("13:31:00+00:00")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["2026-13", "2026", "26-01", "junk", "", "2026-00"])
async def test_data_days_rejects_bad_month(bad):
    with pytest.raises(HTTPException) as exc:
        await data_days(month=bad, user=USER, conn=DaysConn([]))
    assert exc.value.status_code == 400
