"""API response DTOs. Never return SQLAlchemy models directly: these control exactly what
leaves the process (no password_hash, no other tenants' rows reachable by relationship)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(_Out):
    id: uuid.UUID
    email: str
    display_name: str | None


class OrganisationOut(_Out):
    id: uuid.UUID
    name: str
    slug: str


class SessionInfo(BaseModel):
    user: UserOut
    organisation: OrganisationOut
    role: str


class LoginResponse(SessionInfo):
    access_token: str
    token_type: str = "bearer"


class BrandSourceOut(_Out):
    id: uuid.UUID
    brand_profile_id: uuid.UUID
    title: str
    status: str
    sensitivity: str
    created_at: datetime
    updated_at: datetime
