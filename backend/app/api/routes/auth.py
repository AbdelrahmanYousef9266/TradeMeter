"""
Authentication routes:
  GET  /auth/google          → redirect to Google OAuth consent page
  GET  /auth/google/callback → exchange code, upsert user, set session cookie
  POST /auth/nt-token        → generate / display NT connection token
  GET  /auth/nt-status       → return current nt_connected flag
  POST /auth/logout          → clear session cookie
  GET  /auth/me              → return current user profile
"""

import logging

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
from app.models.user import NTTokenResponse, User

logger = logging.getLogger(__name__)
router = APIRouter()

_GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"

_COOKIE_NAME = "tm_session"
_COOKIE_OPTS = {
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
        raise HTTPException(501, "Google OAuth not configured — set GOOGLE_CLIENT_ID")

    params = (
        f"?client_id={settings.google_client_id}"
        f"&redirect_uri={settings.google_redirect_uri}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        "&access_type=offline"
        "&prompt=select_account"
    )
    return RedirectResponse(_GOOGLE_AUTH_URL + params)


@router.get("/google/callback")
async def google_callback(code: str, response: Response, conn=Depends(get_db)):
    """Exchange authorization code for user info and issue a session cookie."""
    if not settings.google_client_id:
        raise HTTPException(501, "Google OAuth not configured")

    async with httpx.AsyncClient() as client:
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
            raise HTTPException(401, "Google token exchange failed")

        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(401, "No access_token in Google response")

        info_resp = await client.get(
            _GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_resp.status_code != 200:
            raise HTTPException(401, "Failed to fetch Google user info")

        info = info_resp.json()

    email     = info.get("email")
    google_id = info.get("sub")

    if not email or not google_id:
        raise HTTPException(401, "Incomplete user info from Google")

    row = await conn.fetchrow(
        """INSERT INTO users (email, google_id)
           VALUES ($1, $2)
           ON CONFLICT (email) DO UPDATE
               SET google_id = EXCLUDED.google_id
           RETURNING *""",
        email, google_id,
    )
    user = User(**dict(row))

    jwt_token = create_jwt(str(user.id), user.email, user.nt_connected)
    response.set_cookie(_COOKIE_NAME, jwt_token, **_COOKIE_OPTS)
    return {"status": "ok", "email": user.email}


# ── NT connection token ─────────────────────────────────────────────────────

@router.post("/nt-token", response_model=NTTokenResponse)
async def issue_nt_token(
    user: User = Depends(get_current_user),
    conn=Depends(get_db),
) -> NTTokenResponse:
    """
    Generate and return the user's NT connection token.

    The plain token is returned exactly once.  Subsequent calls return only the
    prefix so the UI can display it without re-exposing the secret.
    """
    if user.nt_token_hash is not None:
        return NTTokenResponse(
            token="",
            prefix=user.nt_token_prefix or "",
            connected=user.nt_connected,
        )

    plain_token = generate_nt_token()
    token_hash  = hash_nt_token(plain_token)
    prefix      = plain_token[:6]  # "TM-XXX" — first 6 chars

    await conn.execute(
        """UPDATE users
           SET nt_token_hash = $1, nt_token_prefix = $2
           WHERE id = $3""",
        token_hash, prefix, user.id,
    )

    return NTTokenResponse(token=plain_token, prefix=prefix, connected=False)


@router.get("/nt-status")
async def nt_status(user: User = Depends(get_current_user)) -> dict:
    return {
        "connected":    user.nt_connected,
        "last_seen":    user.nt_last_seen.isoformat() if user.nt_last_seen else None,
        "has_token":    user.nt_token_hash is not None,
        "token_prefix": user.nt_token_prefix,
    }


# ── Session management ──────────────────────────────────────────────────────

@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(_COOKIE_NAME)
    return {"status": "logged out"}


@router.get("/me", response_model=User)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
