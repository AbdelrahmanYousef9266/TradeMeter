"""
Eastern-Time / DST conversion tests.

Playback replays bars from arbitrary historical dates, so the ET conversion
must respect the real US DST transition dates — not a fixed month heuristic.
The regression case is mid-March: DST is already active but the month is still
3, which the old April–October heuristic classified as EST (off by one hour).
"""

from datetime import datetime, timezone

from app.services.market_data.features import _to_et, _is_us_eastern_dst, _nth_sunday


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_nth_sunday_transition_dates():
    # DST 2025 starts 2nd Sunday of March (Mar 9), ends 1st Sunday of Nov (Nov 2).
    assert _nth_sunday(2025, 3, 2) == 9
    assert _nth_sunday(2025, 11, 1) == 2
    # 2026: 2nd Sunday March = Mar 8; 1st Sunday Nov = Nov 1.
    assert _nth_sunday(2026, 3, 2) == 8
    assert _nth_sunday(2026, 11, 1) == 1


def test_winter_is_est():
    # January → EST (UTC-5): 14:30 UTC → 09:30 ET.
    et = _to_et(_utc(2025, 1, 15, 14, 30))
    assert (et.hour, et.minute) == (9, 30)
    assert _is_us_eastern_dst(_utc(2025, 1, 15, 14, 30)) is False


def test_summer_is_edt():
    # July → EDT (UTC-4): 14:30 UTC → 10:30 ET.
    et = _to_et(_utc(2025, 7, 15, 14, 30))
    assert (et.hour, et.minute) == (10, 30)
    assert _is_us_eastern_dst(_utc(2025, 7, 15, 14, 30)) is True


def test_mid_march_is_edt_regression():
    """The old month heuristic wrongly treated mid-March as EST. It is EDT."""
    # March 15 2025 is after the Mar 9 transition → EDT → 14:30 UTC = 10:30 ET.
    assert _is_us_eastern_dst(_utc(2025, 3, 15, 14, 30)) is True
    et = _to_et(_utc(2025, 3, 15, 14, 30))
    assert (et.hour, et.minute) == (10, 30)

    # March 3 2025 is before the transition → still EST → 09:30 ET.
    assert _is_us_eastern_dst(_utc(2025, 3, 3, 14, 30)) is False
    et_before = _to_et(_utc(2025, 3, 3, 14, 30))
    assert (et_before.hour, et_before.minute) == (9, 30)


def test_early_november_is_edt():
    """Nov 1 2025 is before the Nov 2 fall-back → still EDT."""
    assert _is_us_eastern_dst(_utc(2025, 11, 1, 14, 30)) is True
    # Nov 10 is after → EST.
    assert _is_us_eastern_dst(_utc(2025, 11, 10, 14, 30)) is False
