from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class User(BaseModel):
    id: UUID
    email: str
    google_id: str
    nt_token_hash: str | None = None
    nt_token_prefix: str | None = None   # masked display value only (e.g. "TM-••••")
    nt_token_lookup: str | None = None   # SHA-256 hex lookup index — never the plaintext
    nt_connected: bool = False
    nt_last_seen: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: str
    google_id: str


class NTTokenResponse(BaseModel):
    token: str | None  # full plain token on first issue; None on subsequent calls
    prefix: str        # first 6 chars kept plain ("TM-A3F...")
    connected: bool
    first_issue: bool  # True only on the very first call — show the "save this" warning

class UserPublic(BaseModel):
    """Subset of User safe to expose to the frontend — no token hash."""
    id: UUID
    email: str
    nt_connected: bool

    class Config:
        from_attributes = True
