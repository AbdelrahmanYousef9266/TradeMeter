"""
Phase 5 test suite — Google OAuth flow, NT token lifecycle, session management.

No real database or Redis required — get_db is overridden via
FastAPI's dependency_overrides for all DB-touching tests.

Run with: cd backend && pytest tests/test_phase5.py -v
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_jwt, generate_nt_token, hash_nt_token, verify_nt_token
from app.db.database import get_db


# ── Lifespan stub ────────────────────────────────────────────────────────────

@asynccontextmanager
async def _noop_lifespan(app):
    app.state.db_pool        = MagicMock()  # prevent AttributeError if reached
    app.state.redis          = None
    app.state.tcp_task       = None
    app.state.ingestion_task = None
    yield


def _client_with_db(mock_conn):
    """Return a TestClient with get_db overridden to yield mock_conn."""
    from app.main import app
    app.router.lifespan_context = _noop_lifespan

    async def _override():
        yield mock_conn

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=True)
    return client, app


def _fake_user_row(
    user_id: uuid.UUID | None = None,
    nt_connected: bool = False,
    nt_token_hash: str | None = None,
    nt_token_prefix: str | None = None,
    nt_last_seen: datetime | None = None,
) -> dict:
    return {
        "id":              user_id or uuid.uuid4(),
        "email":           "test@example.com",
        "google_id":       "google-123",
        "nt_token_hash":   nt_token_hash,
        "nt_token_prefix": nt_token_prefix,
        "nt_connected":    nt_connected,
        "nt_last_seen":    nt_last_seen,
        "created_at":      datetime.now(tz=timezone.utc),
    }


def _mock_conn_for(row: dict) -> AsyncMock:
    """AsyncMock connection whose fetchrow() returns an asyncpg-like record."""
    record = MagicMock()
    record.__getitem__ = lambda self, k: row[k]
    record.keys        = lambda self=None: row.keys()
    for k, v in row.items():
        setattr(record, k, v)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=record)
    conn.execute  = AsyncMock(return_value=None)
    return conn


# ── Test 1: GET /auth/google → 302 redirect to Google ───────────────────────

def test_google_login_redirects():
    from app.main import app
    app.router.lifespan_context = _noop_lifespan

    with patch("app.core.config.settings.google_client_id", "fake-client-id"):
        client   = TestClient(app, raise_server_exceptions=True)
        response = client.get("/auth/google", follow_redirects=False)

    assert response.status_code in (302, 307)
    location = response.headers.get("location", "")
    assert "accounts.google.com" in location, f"Expected Google in location, got: {location}"
    assert "fake-client-id" in location
    assert "select_account" in location


# ── Test 2: GET /auth/me without cookie → 401 ───────────────────────────────

def test_me_no_cookie():
    row  = _fake_user_row()
    conn = _mock_conn_for(row)
    client, app = _client_with_db(conn)
    try:
        response = client.get("/auth/me")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


# ── Test 3: GET /auth/me with valid JWT cookie → public user data ────────────

def test_me_with_valid_cookie():
    row  = _fake_user_row()
    conn = _mock_conn_for(row)
    token = create_jwt(str(row["id"]), row["email"], False)

    client, app = _client_with_db(conn)
    try:
        response = client.get("/auth/me", cookies={"tm_session": token})
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert "nt_connected" in data
        assert "nt_token_hash" not in data    # must NOT leak the hash
        assert "google_id"     not in data    # must NOT expose google ID
    finally:
        app.dependency_overrides.clear()


# ── Test 4: POST /auth/logout → cookie cleared ───────────────────────────────

def test_logout_clears_cookie():
    from app.main import app
    app.router.lifespan_context = _noop_lifespan

    client   = TestClient(app, raise_server_exceptions=True)
    response = client.post("/auth/logout")

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "tm_session" in set_cookie
    # Starlette signals deletion via max-age=0
    assert "max-age=0" in set_cookie.lower()


# ── Test 5: GET /auth/nt-token without auth cookie → 401 ────────────────────

def test_nt_token_requires_auth():
    row  = _fake_user_row()
    conn = _mock_conn_for(row)
    client, app = _client_with_db(conn)
    try:
        response = client.get("/auth/nt-token")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


# ── Test 6: generate_nt_token() format ───────────────────────────────────────

def test_generate_nt_token_format():
    for _ in range(30):
        token = generate_nt_token()
        assert token.startswith("TM-"), f"Token must start with TM-: {token!r}"
        assert len(token) == 9,         f"Token must be 9 chars: {token!r}"
        suffix = token[3:]
        assert suffix.isalnum() and suffix.isupper(), f"Suffix must be uppercase alnum: {suffix!r}"


# ── Test 7: hash + verify round-trip ────────────────────────────────────────

def test_hash_verify_roundtrip():
    token  = generate_nt_token()
    hashed = hash_nt_token(token)

    assert     verify_nt_token(token,      hashed), "Must return True for correct token"
    assert not verify_nt_token("TM-WRONG1",hashed), "Must return False for wrong token"
    assert not verify_nt_token("",         hashed), "Must return False for empty string"


# ── Test 8: GET /auth/nt-status → connected=false when nt_last_seen=None ────

def test_nt_status_disconnected_no_last_seen():
    row  = _fake_user_row(nt_connected=False, nt_last_seen=None)
    conn = _mock_conn_for(row)
    token = create_jwt(str(row["id"]), row["email"], False)

    client, app = _client_with_db(conn)
    try:
        response = client.get("/auth/nt-status", cookies={"tm_session": token})
        assert response.status_code == 200
        assert response.json()["connected"] is False
    finally:
        app.dependency_overrides.clear()


# ── Test 9: nt_status returns connected=false for stale last_seen (>30s) ────

def test_nt_status_stale_last_seen():
    stale = datetime.now(tz=timezone.utc) - timedelta(seconds=60)
    row   = _fake_user_row(nt_connected=True, nt_last_seen=stale)
    conn  = _mock_conn_for(row)
    token = create_jwt(str(row["id"]), row["email"], True)

    client, app = _client_with_db(conn)
    try:
        response = client.get("/auth/nt-status", cookies={"tm_session": token})
        assert response.status_code == 200
        assert response.json()["connected"] is False, "Stale last_seen must yield connected=False"
        # The endpoint must have attempted to update nt_connected=false in DB
        conn.execute.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()


# ── Test 10: upsert_user is idempotent ───────────────────────────────────────

def test_upsert_user_idempotent():
    from app.db.database import upsert_user

    uid          = uuid.uuid4()
    returned_row = {
        "id": uid, "email": "u@example.com", "google_id": "g-001",
        "nt_token_hash": None, "nt_token_prefix": None,
        "nt_connected": False, "nt_last_seen": None,
        "created_at": datetime.now(tz=timezone.utc),
    }
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=returned_row)

    async def run():
        r1 = await upsert_user(conn, "u@example.com", "g-001")
        r2 = await upsert_user(conn, "u@example.com", "g-001")
        return r1, r2

    r1, r2 = asyncio.run(run())

    assert r1["email"]     == "u@example.com"
    assert r2["email"]     == "u@example.com"
    assert conn.fetchrow.await_count == 2  # called both times (upsert = ON CONFLICT DO UPDATE)
