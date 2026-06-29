"""
Phase 2 test suite — pure unit tests for the core components that need no
running database or Redis instance.

Run with:
    cd backend && pytest tests/test_phase2.py -v
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import generate_nt_token, hash_nt_token, verify_nt_token
from app.models.tick import RawMessage, Tick
from app.services.market_data.features import FeatureEngine


# ── Helpers ─────────────────────────────────────────────────────────────────

def _raw_line(
    token: str = "TM-ABCDEF",
    timestamp: str = "2025-01-01T10:00:00Z",
    symbol: str = "MES 03-25",
    open_: float = 5000.00,
    high: float = 5001.00,
    low: float = 4999.00,
    close: float = 5000.50,
    volume: int = 100,
    bar_type: str = "1min",
) -> str:
    return (
        f"{token}|{timestamp}|{symbol}|{open_:.2f}|{high:.2f}"
        f"|{low:.2f}|{close:.2f}|{volume}|{bar_type}"
    )


def _make_tick(
    close: float = 5000.0,
    high: float = 5001.0,
    low: float = 4999.0,
    volume: int = 200,
) -> Tick:
    return Tick(
        time=datetime.now(tz=timezone.utc),
        user_id=uuid.uuid4(),
        symbol="MES 03-25",
        open=close - 0.25,
        high=high,
        low=low,
        close=close,
        volume=volume,
        bar_type="1min",
    )


# ── Test 1: RawMessage.parse() — valid message ───────────────────────────────

def test_raw_message_parse_valid():
    line = _raw_line()
    msg = RawMessage.parse(line)

    assert msg.token == "TM-ABCDEF"
    assert msg.symbol == "MES 03-25"
    assert msg.open   == pytest.approx(5000.00)
    assert msg.high   == pytest.approx(5001.00)
    assert msg.low    == pytest.approx(4999.00)
    assert msg.close  == pytest.approx(5000.50)
    assert msg.volume == 100
    assert msg.bar_type == "1min"
    assert isinstance(msg.timestamp, datetime)


# ── Test 2: RawMessage.parse() — malformed messages ─────────────────────────

@pytest.mark.parametrize("bad_line", [
    "",                              # empty
    "TM-ABCDEF|2025-01-01T10:00:00Z|MES|5000|5001|4999|5000|100",  # 8 fields not 9
    "TM-ABCDEF|not-a-date|MES|5000|5001|4999|5000|100|1min",       # bad timestamp
    "TM-ABCDEF|2025-01-01T10:00:00Z|MES|NOTNUM|5001|4999|5000|100|1min",  # bad OHLC
    "TM-ABCDEF|2025-01-01T10:00:00Z|MES|5000|5001|4999|5000|NOINT|1min", # bad volume
])
def test_raw_message_parse_malformed(bad_line):
    with pytest.raises(ValueError):
        RawMessage.parse(bad_line)


# ── Test 3: FeatureEngine warmup ─────────────────────────────────────────────

def test_feature_engine_warmup():
    engine = FeatureEngine()

    # First 49 bars must return None
    for _ in range(49):
        result = engine.update(_make_tick())
        assert result is None, "Expected None during warmup"

    # 50th bar must return a feature dict with all 10 keys
    result = engine.update(_make_tick())
    assert result is not None, "Expected feature dict on bar 50"
    assert isinstance(result, dict)

    expected_keys = {
    "rsi_14", "ema_9", "ema_21", "ema_50",
    "macd", "macd_signal", "atr_14",
    "volume_delta", "bar_range", "close_position",
    "vwap", "vwap_distance", "vwap_cross",
    "session_minutes", "session_phase", "is_power_hour",
}
    assert set(result.keys()) == expected_keys


# ── Test 4: close_position always in [0.0, 1.0] ─────────────────────────────

def test_feature_engine_close_position_range():
    engine = FeatureEngine()
    prices = [5000.0 + i * 0.25 for i in range(200)]

    for i, price in enumerate(prices):
        high  = price + 1.0
        low   = price - 1.0
        close = price
        result = engine.update(_make_tick(close=close, high=high, low=low))
        if result is not None:
            cp = result["close_position"]
            assert 0.0 <= cp <= 1.0, f"close_position={cp} out of range on bar {i+1}"


# ── Test 5: generate_nt_token format ─────────────────────────────────────────

def test_generate_nt_token_format():
    for _ in range(20):
        token = generate_nt_token()
        assert token.startswith("TM-"), f"Token does not start with 'TM-': {token!r}"
        assert len(token) == 9, f"Token length is {len(token)}, expected 9: {token!r}"
        # Chars after "TM-" should be uppercase alphanumeric
        suffix = token[3:]
        assert suffix.isalnum() and suffix.isupper(), f"Unexpected chars in suffix: {suffix!r}"


# ── Test 6: hash / verify round-trip ─────────────────────────────────────────

def test_nt_token_hash_verify_roundtrip():
    token  = generate_nt_token()
    hashed = hash_nt_token(token)

    assert verify_nt_token(token, hashed), "verify_nt_token returned False for correct token"
    assert not verify_nt_token("TM-WRONG1", hashed), "verify_nt_token returned True for wrong token"


# ── Test 7: GET /health returns 200 ──────────────────────────────────────────

@asynccontextmanager
async def _noop_lifespan(app):
    """Minimal lifespan that sets dummy state so routes don't crash on import."""
    app.state.db_pool     = None
    app.state.redis       = None
    app.state.tcp_task    = None
    app.state.ingestion_task = None
    yield


def test_health_endpoint():
    from app.main import app

    # Override the lifespan so we don't need real DB/Redis in CI.
    app.router.lifespan_context = _noop_lifespan

    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
