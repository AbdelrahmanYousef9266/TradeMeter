"""
Authentication routes:
  GET  /auth/google          → redirect to Google OAuth consent page
  GET  /auth/google/callback → exchange code, upsert user, set session cookie,
                               redirect browser to frontend /dashboard
  GET  /auth/nt-token        → issue or display NT connection token
  GET  /auth/nt-status       → current nt_connected status (30-second staleness check)
  POST /auth/logout          → clear session cookie
  GET  /auth/me              → return current user's public profile
"""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.security import (
    create_jwt,
    generate_nt_token,
    hash_nt_token,
    nt_token_lookup_hash,
    get_current_user,
)
from app.db.database import get_db
from app.models.user import NTTokenResponse, User, UserPublic

logger = logging.getLogger(__name__)
router = APIRouter()

_GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v2/userinfo"

_COOKIE_NAME       = "tm_session"
_OAUTH_STATE_COOKIE    = "tm_oauth_state"
_OAUTH_VERIFIER_COOKIE = "tm_oauth_verifier"
_OAUTH_TTL_SECONDS     = 600   # the consent round-trip must complete within 10 min

# Displayed in place of the real NT token — the plaintext is never stored/returned.
_MASKED_TOKEN = "TM-••••"


def _cookie_opts() -> dict:
    return {
        "httponly": True,
        "secure":   settings.env == "production",
        "samesite": "lax",
        "max_age":  settings.jwt_expire_hours * 3600,
    }


def _oauth_cookie_opts() -> dict:
    """Short-lived httpOnly cookies carrying the OAuth CSRF state + PKCE verifier."""
    return {
        "httponly": True,
        "secure":   settings.env == "production",
        "samesite": "lax",   # sent on the top-level GET redirect back from Google
        "max_age":  _OAUTH_TTL_SECONDS,
    }


def _pkce_challenge(verifier: str) -> str:
    """S256 PKCE challenge: base64url(sha256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


# ── Google OAuth ────────────────────────────────────────────────────────────

@router.get("/google")
async def google_login():
    """Redirect the browser to Google's OAuth consent page."""
    if not settings.google_client_id:
        raise HTTPException(
            501,
            detail=(
                "Google OAuth not configured. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env. "
                "Create credentials at https://console.cloud.google.com → "
                "APIs & Services → Credentials → Create OAuth 2.0 Client ID. "
                f"Redirect URI: {settings.google_redirect_uri}"
            ),
        )

    # CSRF protection: a random `state` is echoed back by Google and must match
    # the value we stash in an httpOnly cookie — this defeats login-CSRF /
    # session-fixation, where an attacker feeds the victim their own `code`.
    # PKCE (S256) additionally binds the code to this browser session.
    state    = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)

    params = urlencode({
        "client_id":             settings.google_client_id,
        "redirect_uri":          settings.google_redirect_uri,
        "response_type":         "code",
        "scope":                 "openid email profile",
        "access_type":           "offline",
        "prompt":                "select_account",
        "state":                 state,
        "code_challenge":        _pkce_challenge(verifier),
        "code_challenge_method": "S256",
    })
    response = RedirectResponse(_GOOGLE_AUTH_URL + "?" + params)
    response.set_cookie(_OAUTH_STATE_COOKIE,    state,    **_oauth_cookie_opts())
    response.set_cookie(_OAUTH_VERIFIER_COOKIE, verifier, **_oauth_cookie_opts())
    return response


@router.get("/google/callback")
async def google_callback(code: str, request: Request, state: str = "", conn=Depends(get_db)):
    """
    Exchange the authorization code Google sends us for user info,
    upsert the user in our DB, issue a JWT, set it as an httpOnly cookie,
    and redirect the browser to the frontend dashboard.

    Rejects the request unless the `state` query parameter matches the value
    stored in the httpOnly cookie set at /auth/google (CSRF protection).
    """
    if not settings.google_client_id:
        raise HTTPException(501, "Google OAuth not configured")

    # ── CSRF state check ──────────────────────────────────────────────────
    expected_state = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not expected_state or not state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(400, "Invalid OAuth state — possible CSRF, please retry login")

    verifier = request.cookies.get(_OAUTH_VERIFIER_COOKIE) or ""

    async with httpx.AsyncClient() as client:
        # Step 1: exchange code for tokens
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri":  settings.google_redirect_uri,
                "grant_type":    "authorization_code",
                "code_verifier": verifier,
            },
        )
        if token_resp.status_code != 200:
            logger.error("Google token exchange failed: %s", token_resp.text)
            raise HTTPException(400, "Google token exchange failed")

        token_json = token_resp.json()
        access_token = token_json.get("access_token")
        if not access_token:
            raise HTTPException(400, "No access_token in Google response")

        # Step 2: fetch user info
        info_resp = await client.get(
            _GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_resp.status_code != 200:
            raise HTTPException(400, "Failed to fetch Google user info")

        info = info_resp.json()

    email     = info.get("email")
    google_id = info.get("id")  # v2 userinfo uses "id" not "sub"

    if not email or not google_id:
        raise HTTPException(400, "Incomplete user info from Google")

    # Step 3: upsert user
    row = await conn.fetchrow(
        """INSERT INTO users (email, google_id)
           VALUES ($1, $2)
           ON CONFLICT (email) DO UPDATE
               SET google_id = EXCLUDED.google_id
           RETURNING *""",
        email, google_id,
    )
    user = User(**dict(row))

    # Step 4: issue JWT
    jwt_token = create_jwt(str(user.id), user.email, user.nt_connected)

    # Step 5: set cookie + redirect to frontend
    redirect_url = f"{settings.frontend_url}/dashboard"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(_COOKIE_NAME, jwt_token, **_cookie_opts())
    # One-time OAuth cookies are consumed — clear them.
    response.delete_cookie(_OAUTH_STATE_COOKIE,    samesite="lax")
    response.delete_cookie(_OAUTH_VERIFIER_COOKIE, samesite="lax")
    return response


# ── NT connection token ─────────────────────────────────────────────────────

@router.get("/nt-token", response_model=NTTokenResponse)
async def get_nt_token(
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> NTTokenResponse:
    """
    Return the user's NT connection token.

    On the very first call the full plain token is returned and `first_issue=True`.
    The token is never stored in plain text — only its bcrypt hash.
    All subsequent calls return `token=None` with only the saved prefix.
    """
    if user.nt_token_hash is not None:
        # Token was already issued — return only the masked display value.
        return NTTokenResponse(
            token=None,
            prefix=user.nt_token_prefix or _MASKED_TOKEN,
            connected=user.nt_connected,
            first_issue=False,
        )

    # First issue — the plaintext is returned to the user exactly once and NEVER
    # persisted. We store: a bcrypt hash (final verification), a SHA-256 lookup
    # index (queryable), and a masked display string.
    plain_token = generate_nt_token()       # e.g. "TM-ZVE9X2" (9 chars)
    token_hash  = hash_nt_token(plain_token)
    token_lookup = nt_token_lookup_hash(plain_token)

    await conn.execute(
        """UPDATE users
           SET nt_token_hash = $1, nt_token_lookup = $2, nt_token_prefix = $3
           WHERE id = $4""",
        token_hash, token_lookup, _MASKED_TOKEN, user.id,
    )

    return NTTokenResponse(
        token=plain_token,
        prefix=_MASKED_TOKEN,
        connected=False,
        first_issue=True,
    )


async def compute_nt_connected(user: User, conn) -> bool:
    """
    Return whether NT is currently connected for *user*, applying the 30-second
    staleness rule: if the last heartbeat is older than 30s, mark the user
    disconnected in the DB and return False.

    Shared by GET /auth/nt-status and GET /market/status so the staleness logic
    (and its DB side effect) lives in exactly one place.
    """
    connected = user.nt_connected

    if connected and user.nt_last_seen is not None:
        now       = datetime.now(tz=timezone.utc)
        last_seen = user.nt_last_seen
        # Ensure timezone-aware for comparison
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        if (now - last_seen).total_seconds() > 30:
            connected = False
            await conn.execute(
                "UPDATE users SET nt_connected = false WHERE id = $1",
                user.id,
            )
            logger.info("NT connection stale for user %s — marked disconnected", user.id)

    return connected


@router.get("/nt-status")
async def nt_status(
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> dict:
    """
    Return the current NT connection status.
    A connection is considered stale if nt_last_seen is older than 30 seconds;
    in that case the DB is updated to reflect disconnection.
    """
    connected = await compute_nt_connected(user, conn)

    return {
        "connected":    connected,
        "last_seen":    user.nt_last_seen.isoformat() if user.nt_last_seen else None,
        "has_token":    user.nt_token_hash is not None,
        "token_prefix": user.nt_token_prefix,
    }


# ── Session management ──────────────────────────────────────────────────────

@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(_COOKIE_NAME, samesite="lax")
    return {"status": "logged out"}


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(get_current_user)) -> UserPublic:
    """Return the authenticated user's public profile (no token hash)."""
    return UserPublic(id=user.id, email=user.email, nt_connected=user.nt_connected)
