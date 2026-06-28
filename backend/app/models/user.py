from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class User(BaseModel):
    id: UUID
    email: str
    google_id: str
    nt_token_hash: str | None = None
    nt_token_prefix: str | None = None
    nt_connected: bool = False
    nt_last_seen: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: str
    google_id: str


class NTTokenResponse(BaseModel):
    token: str      # plain token shown to user once only; empty string on repeat calls
    prefix: str     # first 6 chars kept plain for UI display ("TM-A3F...")
    connected: bool
