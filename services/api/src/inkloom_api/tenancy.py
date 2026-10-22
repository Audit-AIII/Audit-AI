"""Tenant-scoped lookups (phase2_auth_and_tenant_scoping.md task 5).

Every read and write must filter by organisation, directly or through a verified parent. The
pattern here is: fetch by primary key, then check the row's own `organisation_id` — or, for a
table with no such column (e.g. `BrandSource`, which only has `brand_profile_id`), check its
parent's. A row that exists but belongs to another organisation raises the same 404 as a row
that doesn't exist at all (task 7: never leak whether another tenant's record exists).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import BrandProfile


def not_found(detail: str = "not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail)


def get_brand_profile_or_404(db: Session, organisation_id: uuid.UUID, brand_profile_id: uuid.UUID) -> BrandProfile:
    profile = db.get(BrandProfile, brand_profile_id)
    if profile is None or profile.organisation_id != organisation_id:
        raise not_found("brand not found")
    return profile
