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

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.security import (
    create_jwt,
    generate_nt_token,
    hash_nt_token,
    get_current_user,
)
from app.db.database import get_db
from app.models.user import NTTokenResponse, User, UserPublic

logger = logging.getLogger(__name__)
router = APIRouter()

_GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v2/userinfo"

_COOKIE_NAME = "tm_session"


def _cookie_opts() -> dict:
    return {
        "httponly": True,
        "secure":   settings.env == "production",
        "samesite": "lax",
        "max_age":  settings.jwt_expire_hours * 3600,
    }


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

    params = urlencode({
        "client_id":     settings.google_client_id,
        "redirect_uri":  settings.google_redirect_uri,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
        "prompt":        "select_account",
    })
    return RedirectResponse(_GOOGLE_AUTH_URL + "?" + params)


@router.get("/google/callback")
async def google_callback(code: str, conn=Depends(get_db)):
    """
    Exchange the authorization code Google sends us for user info,
    upsert the user in our DB, issue a JWT, set it as an httpOnly cookie,
    and redirect the browser to the frontend dashboard.
    """
    if not settings.google_client_id:
        raise HTTPException(501, "Google OAuth not configured")

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
        # Token was already issued — return prefix only
        return NTTokenResponse(
            token=None,
            prefix=user.nt_token_prefix or "",
            connected=user.nt_connected,
            first_issue=False,
        )

    # First issue
    plain_token = generate_nt_token()       # e.g. "TM-ZVE9X2" (9 chars)
    token_hash  = hash_nt_token(plain_token)
    prefix      = plain_token              # store FULL token for exact TCP lookup

    await conn.execute(
        """UPDATE users
           SET nt_token_hash = $1, nt_token_prefix = $2
           WHERE id = $3""",
        token_hash, prefix, user.id,
    )

    return NTTokenResponse(
        token=plain_token,
        prefix=prefix,
        connected=False,
        first_issue=True,
    )


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
    now       = datetime.now(tz=timezone.utc)
    connected = user.nt_connected

    if connected and user.nt_last_seen is not None:
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


@router.get("/debug/token-check")
async def debug_token_check(conn=Depends(get_db)):
    """Temporary debug endpoint — remove after confirming token validation works."""
    rows = await conn.fetch(
        "SELECT id, email, nt_token_prefix, nt_token_hash IS NOT NULL AS has_hash FROM users"
    )
    return [dict(r) for r in rows]


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(get_current_user)) -> UserPublic:
    """Return the authenticated user's public profile (no token hash)."""
    return UserPublic(id=user.id, email=user.email, nt_connected=user.nt_connected)
