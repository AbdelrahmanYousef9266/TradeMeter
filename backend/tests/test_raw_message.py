"""
RawMessage.parse tests — the parser for untrusted network input from the TCP
listener. It is the first line of defense, so its validation must reject every
malformed shape without raising anything but a clean ValueError.
"""

from datetime import timezone

import pytest

from app.models.tick import RawMessage

_VALID = "TM-AAAAAA|2026-06-01T14:30:00Z|MES|5840.0|5841.0|5839.0|5840.5|100|1min"


def test_parses_valid_message():
    msg = RawMessage.parse(_VALID)
    assert msg.token == "TM-AAAAAA"
    assert msg.symbol == "MES"
    assert msg.open == 5840.0 and msg.close == 5840.5
    assert msg.volume == 100
    assert msg.bar_type == "1min"
    # 'Z' suffix parses to a UTC-aware datetime.
    assert msg.timestamp.tzinfo is not None
    assert msg.timestamp.utcoffset() == timezone.utc.utcoffset(None)


@pytest.mark.parametrize("bad", [
    "",                                                   # empty
    "too|few|fields",                                     # wrong field count
    "|2026-06-01T14:30:00Z|MES|1|2|1|1.5|100|1min",       # empty token
    "TM-A|not-a-date|MES|1|2|1|1.5|100|1min",             # bad timestamp
    "TM-A|2026-06-01T14:30:00Z|MES|x|2|1|1.5|100|1min",   # non-numeric price
    "TM-A|2026-06-01T14:30:00Z|MES|1|2|1|1.5|abc|1min",   # non-integer volume
    "TM-A|2026-06-01T14:30:00Z|MES|-1|2|1|1.5|100|1min",  # non-positive price
    "TM-A|2026-06-01T14:30:00Z|MES|1|1|9|1.5|100|1min",   # high < low
    "TM-A|2026-06-01T14:30:00Z|MES|1|2|1|1.5|-5|1min",    # negative volume
])
def test_rejects_malformed(bad):
    with pytest.raises(ValueError):
        RawMessage.parse(bad)


def test_extra_pipe_field_rejected():
    # A 10th field must not be silently accepted.
    with pytest.raises(ValueError):
        RawMessage.parse(_VALID + "|extra")


def test_whitespace_is_stripped():
    msg = RawMessage.parse("  " + _VALID + "  ")
    assert msg.token == "TM-AAAAAA"
    assert msg.bar_type == "1min"
