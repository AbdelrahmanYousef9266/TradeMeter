"""
Data-health refinements:
  FIX 1 — the "complete day" threshold is timeframe-aware (a full 5-min RTH day is
          ~78 bars, not ~390), so 5-min days are no longer all flagged partial.
  FIX 3 — US market holidays are excluded from the "missing weekdays" gap count.
"""

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.api.routes.market import (
    data_integrity, _timeframe_minutes, _complete_day_threshold, _us_market_holidays,
)


USER = SimpleNamespace(id=uuid.uuid4())


class IntegrityConn:
    def __init__(self, day_rows, dup=0):
        self._days = day_rows
        self._dup = dup

    async def fetch(self, q, *a):
        return self._days

    async def fetchval(self, q, *a):
        return self._dup


# ── FIX 1: timeframe-aware completeness threshold ────────────────────────────

def test_timeframe_minutes_parsing():
    assert _timeframe_minutes("1min") == 1
    assert _timeframe_minutes("5min") == 5
    assert _timeframe_minutes("15min") == 15
    assert _timeframe_minutes("garbage") == 1     # safe default
    assert _timeframe_minutes(None) == 1


def test_complete_day_threshold_scales_with_timeframe():
    assert _complete_day_threshold("1min") == 370      # 390 * 0.95
    assert _complete_day_threshold("5min") == 74       # 78 * 0.95 → 74 (≈75)
    assert _complete_day_threshold("15min") == 25      # 26 * 0.95


@pytest.mark.asyncio
async def test_five_min_full_day_is_complete():
    """A ~78-bar 5-min day must classify as complete, not partial."""
    days = [
        {"day": date(2026, 6, 1), "bars": 78},   # full 5-min RTH day
        {"day": date(2026, 6, 2), "bars": 40},   # genuinely partial
    ]
    out = await data_integrity(timeframe="5min", user=USER, conn=IntegrityConn(days))
    assert out["complete_day_threshold"] == 74
    assert out["complete_days"] == 1
    assert out["partial_days"] == 1
    # The very same 78-bar day WOULD be "partial" under the old 1-min threshold.
    out1 = await data_integrity(timeframe="1min", user=USER, conn=IntegrityConn(days))
    assert out1["complete_days"] == 0


# ── FIX 3: market holidays are not gaps ──────────────────────────────────────

def test_holiday_calendar_known_dates():
    h = _us_market_holidays(2025)
    assert date(2025, 1, 1)  in h      # New Year's Day
    assert date(2025, 1, 20) in h      # MLK Day (3rd Mon Jan)
    assert date(2025, 2, 17) in h      # Presidents Day
    assert date(2025, 4, 18) in h      # Good Friday
    assert date(2025, 5, 26) in h      # Memorial Day (last Mon May)
    assert date(2025, 6, 19) in h      # Juneteenth
    assert date(2025, 7, 4)  in h      # Independence Day
    assert date(2025, 9, 1)  in h      # Labor Day
    assert date(2025, 11, 27) in h     # Thanksgiving (4th Thu Nov)
    assert date(2025, 12, 25) in h     # Christmas


def test_holiday_observed_shift():
    # Independence Day 2026 falls on Saturday → observed Friday Jul 3.
    assert date(2026, 7, 3) in _us_market_holidays(2026)
    # Independence Day 2027 falls on Sunday → observed Monday Jul 5.
    assert date(2027, 7, 5) in _us_market_holidays(2027)


@pytest.mark.asyncio
async def test_holidays_excluded_but_real_gaps_flagged():
    # Tue present, Wed genuinely missing, Thu present, Fri = Independence Day
    # (2025-07-04, a market holiday), weekend, Mon present.
    days = [
        {"day": date(2025, 7, 1), "bars": 390},   # Tue
        # 2025-07-02 Wed — genuine gap
        {"day": date(2025, 7, 3), "bars": 390},   # Thu
        # 2025-07-04 Fri — HOLIDAY, must NOT be flagged
        {"day": date(2025, 7, 7), "bars": 390},   # Mon
    ]
    out = await data_integrity(user=USER, conn=IntegrityConn(days))
    dates = out["missing_weekdays"]["dates"]
    assert dates == ["2025-07-02"]                 # only the real gap
    assert out["missing_weekdays"]["count"] == 1
    assert "2025-07-04" not in dates               # holiday excluded
