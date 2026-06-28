import secrets
import string
import logging
import bcrypt
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Depends
from jose import jwt, JWTError

from app.core.config import settings
from app.models.user import User
from app.db.database import get_db

logger = logging.getLogger(__name__)

_TOKEN_ALPHABET = string.ascii_uppercase + string.digits


# ── JWT ────────────────────────────────────────────────────────────────────

def create_jwt(user_id: str, email: str, nt_connected: bool) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub":          user_id,
        "email":        email,
        "nt_connected": nt_connected,
        "iat":          now,
        "exp":          now + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict:
    """Decode and validate JWT. Raises HTTP 401 on any failure."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}")


# ── NT connection token ────────────────────────────────────────────────────

def generate_nt_token() -> str:
    """Return a fresh NT connection token like 'TM-A3F9X2' (9 chars total)."""
    suffix = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(6))
    return f"TM-{suffix}"


def hash_nt_token(token: str) -> str:
    """Return a bcrypt hash of the token for database storage."""
    return bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()


def verify_nt_token(plain_token: str, hashed_token: str) -> bool:
    """Verify a plain token against its stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_token.encode(), hashed_token.encode())
    except Exception:
        return False


# ── FastAPI dependency ─────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    conn=Depends(get_db),
) -> User:
    """
    Read 'tm_session' httpOnly cookie, decode JWT, and return the User row.
    Raises HTTP 401 on any auth failure.
    """
    token = request.cookies.get("tm_session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_jwt(token)  # raises 401 on bad token
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Malformed token payload")

    try:
        uid = _uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user id in token")

    row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", uid)
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    return User(**dict(row))
