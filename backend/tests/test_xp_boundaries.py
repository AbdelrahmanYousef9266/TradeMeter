"""
XP / level boundary tests — numeric edge cases the dashboard depends on:
XP landing exactly on a threshold, surplus carry-over, multi-level jumps, and
the Master (level 100) cap where the per-level threshold is 0.
"""

from app.services.ml.xp import XPTracker, xp_for_level, level_to_rank


def _tracker(level=1, xp=0):
    return XPTracker("u", "scalper", level=level, xp=xp)


def test_xp_exactly_at_threshold_levels_up():
    t = _tracker(level=1, xp=xp_for_level(1))   # exactly 300
    event = t._check_level_up()
    assert event is not None
    assert t.level == 2
    assert t.xp == 0                            # threshold consumed, no surplus


def test_xp_one_below_threshold_does_not_level():
    t = _tracker(level=1, xp=xp_for_level(1) - 1)
    assert t._check_level_up() is None
    assert t.level == 1


def test_surplus_carries_over():
    t = _tracker(level=1, xp=xp_for_level(1) + 50)
    t._check_level_up()
    assert t.level == 2
    assert t.xp == 50


def test_large_xp_jumps_multiple_levels():
    # Enough XP to clear several 300-XP early levels at once.
    t = _tracker(level=1, xp=1000)
    t._check_level_up()
    assert t.level >= 3          # 300 + 300 consumed, 400 surplus → level 3+
    assert t.xp < xp_for_level(t.level)


def test_master_level_is_capped():
    t = _tracker(level=100, xp=999999)
    assert t._check_level_up() is None
    assert t.level == 100
    assert level_to_rank(100) == "Master"
    # xp_for_level returns 0 at Master; to_dict must not divide by zero.
    d = t.to_dict()
    assert d["xp_progress_pct"] == 1.0
    assert d["xp_to_next"] == 0


def test_award_at_threshold_boundary():
    # 290 + (1 bar + 10 correct) = 301 → crosses the 300 threshold to level 2.
    t = _tracker(level=1, xp=290)
    event = t.award(direction_up=0.9, actual_direction=1, prev_pnl=0.0, curr_pnl=0.0)
    assert event is not None
    assert t.level == 2
    assert t.streak == 1
