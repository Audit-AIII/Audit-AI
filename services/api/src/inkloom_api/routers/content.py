"""POST /api/content/{id}/versions, GET /api/content/{id}/history
(phase6_versioning_approval_audit.md tasks 1 and 8).

Creating a version also runs a review on it synchronously (confirmed with the team) — one call,
one result, same pattern as `POST /api/reviews`.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..db import get_db
from ..models import ApprovalEvent, ContentVersion, Review
from ..review_runner import start_review
from ..schemas import (
    ApprovalEventOut,
    ContentHistoryOut,
    ContentVersionHistoryOut,
    NewVersionResponse,
    ReviewOut,
    ReviewSummaryOut,
)
from ..tenancy import get_content_item_or_404

router = APIRouter(prefix="/api/content", tags=["content"])

MAX_CONTENT_CHARS = 100_000  # matches inkloom_verify.schemas.MAX_CONTENT_CHARS


class NewVersionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)


@router.post("/{content_item_id}/versions", response_model=NewVersionResponse, status_code=201)
def create_version(
    content_item_id: uuid.UUID,
    body: NewVersionRequest,
    auth: AuthContext = Depends(require_permission(Permission.SUBMIT)),
    db: Session = Depends(get_db),
) -> NewVersionResponse:
    item = get_content_item_or_404(db, auth.organisation_id, content_item_id)

    previous_current = (
        db.query(ContentVersion).filter_by(content_item_id=item.id, is_current=True).one_or_none()
    )
    next_number = (previous_current.version_number + 1) if previous_current else 1
    if previous_current is not None:
        previous_current.is_current = False
        db.flush()  # the partial unique index would otherwise see two "current" rows at once

    new_version = ContentVersion(
        content_item_id=item.id,
        version_number=next_number,
        text=body.text,
        text_sha256=hashlib.sha256(body.text.encode("utf-8")).hexdigest(),
        is_current=True,
        created_by=auth.user_id,
    )
    db.add(new_version)
    db.flush()

    review = start_review(db, new_version, item.brand_profile_id)
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="content_version.created",
        entity_type="content_version",
        entity_id=new_version.id,
        details={"version_number": next_number, "review_id": str(review.id)},
        request_id=review.request_id,
    )

    db.commit()
    db.refresh(new_version)
    db.refresh(review)
    return NewVersionResponse(
        content_version_id=new_version.id,
        version_number=new_version.version_number,
        is_current=new_version.is_current,
        review=ReviewOut.from_model(review),
    )


@router.get("/{content_item_id}/history", response_model=ContentHistoryOut)
def get_history(
    content_item_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ContentHistoryOut:
    item = get_content_item_or_404(db, auth.organisation_id, content_item_id)
    versions = (
        db.query(ContentVersion)
        .filter_by(content_item_id=item.id)
        .order_by(ContentVersion.version_number)
        .all()
    )

    history = []
    for version in versions:
        reviews = db.query(Review).filter_by(content_version_id=version.id).order_by(Review.created_at).all()
        decisions = (
            db.query(ApprovalEvent)
            .filter_by(content_version_id=version.id)
            .order_by(ApprovalEvent.created_at)
            .all()
        )
        history.append(
            ContentVersionHistoryOut(
                id=version.id,
                version_number=version.version_number,
                is_current=version.is_current,
                created_by=version.created_by,
                created_at=version.created_at,
                reviews=[ReviewSummaryOut.from_model(r) for r in reviews],
                decisions=[ApprovalEventOut.from_model(d, version.version_number) for d in decisions],
            )
        )

    return ContentHistoryOut(content_item_id=item.id, title=item.title, versions=history)
