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

from .models import BrandProfile, BrandSource, ContentItem, ContentVersion, Review


def not_found(detail: str = "not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail)


def get_brand_profile_or_404(db: Session, organisation_id: uuid.UUID, brand_profile_id: uuid.UUID) -> BrandProfile:
    profile = db.get(BrandProfile, brand_profile_id)
    if profile is None or profile.organisation_id != organisation_id:
        raise not_found("brand not found")
    return profile


def get_brand_source_or_404(
    db: Session, organisation_id: uuid.UUID, brand_profile_id: uuid.UUID, source_id: uuid.UUID
) -> BrandSource:
    """Checks all three levels (source exists, belongs to this brand, brand belongs to this
    organisation) and collapses any failure to the same 404 (task 7)."""
    get_brand_profile_or_404(db, organisation_id, brand_profile_id)
    source = db.get(BrandSource, source_id)
    if source is None or source.brand_profile_id != brand_profile_id:
        raise not_found("source not found")
    return source


def get_content_item_or_404(db: Session, organisation_id: uuid.UUID, content_item_id: uuid.UUID) -> ContentItem:
    item = db.get(ContentItem, content_item_id)
    if item is None or item.organisation_id != organisation_id:
        raise not_found("content not found")
    return item


def get_content_version_or_404(
    db: Session, organisation_id: uuid.UUID, content_version_id: uuid.UUID
) -> ContentVersion:
    version = db.get(ContentVersion, content_version_id)
    if version is None:
        raise not_found("content version not found")
    item = db.get(ContentItem, version.content_item_id)
    if item is None or item.organisation_id != organisation_id:  # verified parent
        raise not_found("content version not found")
    return version


def get_review_or_404(db: Session, organisation_id: uuid.UUID, review_id: uuid.UUID) -> Review:
    review = db.get(Review, review_id)
    if review is None:
        raise not_found("review not found")
    try:
        get_content_version_or_404(db, organisation_id, review.content_version_id)  # raises if cross-tenant
    except HTTPException:
        # Same message as a review that doesn't exist: "content version not found" here would
        # tell the caller that this review id is real, just in another account (task 7).
        raise not_found("review not found") from None
    return review
