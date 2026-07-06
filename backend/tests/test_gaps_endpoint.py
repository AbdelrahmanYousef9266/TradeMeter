"""
/market/gaps — NT-token-authenticated, plain-text coverage for the strategy's
gap-fill import. Verifies token auth (query + header), the per-IP bad-token rate
limit, day aggregation, and the exact plain-text format the NinjaScript parses.
"""

import uuid
from datetime import datetime, date, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import market
from app.api.routes.market import data_gaps


def _dt(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, q, *a):
        return self._rows


class _Acquire:
    def __init__(self, conn):
        self._c = conn

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *e):
        return False


class _Pool:
    def __init__(self, rows):
        self._c = _Conn(rows)

    def acquire(self):
        return _Acquire(self._c)


class _Headers(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


def _req(rows=None, headers=None, ip="1.2.3.4"):
    app = SimpleNamespace(state=SimpleNamespace(db_pool=_Pool(rows or []), redis=object()))
    return SimpleNamespace(client=SimpleNamespace(host=ip), headers=_Headers(headers or {}), app=app)


@pytest.fixture(autouse=True)
def _clear_rate_state():
    market._gap_auth_failures.clear()
    yield
    market._gap_auth_failures.clear()


def _mock_resolve(monkeypatch, value):
    async def fake(token, pool, redis):
        fake.last_token = token
        return value
    fake.last_token = None
    monkeypatch.setattr(market, "_resolve_token", fake)
    return fake


@pytest.mark.asyncio
async def test_valid_token_returns_plaintext_coverage(monkeypatch):
    _mock_resolve(monkeypatch, str(uuid.uuid4()))
    rows = [
        {"day": date(2026, 6, 5), "bars": 390, "first_bar": _dt(2026, 6, 5, 13, 31), "last_bar": _dt(2026, 6, 5, 20, 0)},
        {"day": date(2026, 6, 6), "bars": 200, "first_bar": _dt(2026, 6, 6, 13, 31), "last_bar": _dt(2026, 6, 6, 17, 0)},
    ]
    out = await data_gaps(_req(rows), token="TM-ABC123")
    lines = out.strip().split("\n")

    assert "2026-06-05,390,13:31,20:00" in lines
    assert "2026-06-06,200,13:31,17:00" in lines
    # LAST is the newest bar time across all days (2026-06-06 17:00Z).
    assert lines[-1] == "LAST,2026-06-06T17:00:00Z"


@pytest.mark.asyncio
async def test_query_and_header_token_both_accepted(monkeypatch):
    fake = _mock_resolve(monkeypatch, str(uuid.uuid4()))

    await data_gaps(_req([]), token="TM-QUERY")
    assert fake.last_token == "TM-QUERY"

    await data_gaps(_req([], headers={"X-NT-Token": "TM-HEADER"}), token="")
    assert fake.last_token == "TM-HEADER"


@pytest.mark.asyncio
async def test_empty_db_returns_empty_body(monkeypatch):
    _mock_resolve(monkeypatch, str(uuid.uuid4()))
    out = await data_gaps(_req([]), token="TM-ABC123")
    assert out == ""


@pytest.mark.asyncio
async def test_missing_token_rejected(monkeypatch):
    _mock_resolve(monkeypatch, str(uuid.uuid4()))
    with pytest.raises(HTTPException) as exc:
        await data_gaps(_req([]), token="")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_401_and_records_failure(monkeypatch):
    _mock_resolve(monkeypatch, None)   # token doesn't resolve
    with pytest.raises(HTTPException) as exc:
        await data_gaps(_req([], ip="5.5.5.5"), token="TM-BAD")
    assert exc.value.status_code == 401
    assert len(market._gap_auth_failures["5.5.5.5"]) == 1


@pytest.mark.asyncio
async def test_rate_limited_after_repeated_bad_tokens(monkeypatch):
    _mock_resolve(monkeypatch, None)
    ip = "9.9.9.9"
    for _ in range(market._GAP_AUTH_MAX_FAILURES):
        with pytest.raises(HTTPException) as exc:
            await data_gaps(_req([], ip=ip), token="TM-BAD")
        assert exc.value.status_code == 401
    # The next attempt is throttled before the token is even checked.
    with pytest.raises(HTTPException) as exc:
        await data_gaps(_req([], ip=ip), token="TM-BAD")
    assert exc.value.status_code == 429
