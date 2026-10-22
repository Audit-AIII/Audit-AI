"""POST /api/reviews, GET /api/reviews/{id} (phase3_vertical_slice.md).
POST /api/reviews/{id}/rerun (phase6_versioning_approval_audit.md task 2).

Analysis runs synchronously (confirmed with the team): the request blocks until the engine
finishes, and the response already carries the final findings. No polling in this phase.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from inkloom_verify.schemas import MAX_CONTENT_CHARS
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..db import get_db
from ..models import ContentItem, ContentVersion
from ..review_runner import start_review
from ..schemas import ReviewOut
from ..tenancy import get_brand_profile_or_404, get_review_or_404

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class ReviewCreateRequest(BaseModel):
    brand_id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)
    text: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)


@router.post("", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def create_review(
    body: ReviewCreateRequest,
    auth: AuthContext = Depends(require_permission(Permission.SUBMIT)),
    db: Session = Depends(get_db),
) -> ReviewOut:
    if not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "text must not be blank")
    # brand_id is checked against the authenticated organisation here — never trusted as-is.
    brand = get_brand_profile_or_404(db, auth.organisation_id, body.brand_id)

    content_item = ContentItem(
        organisation_id=auth.organisation_id,
        brand_profile_id=brand.id,
        title=body.title or body.text[:80],
        created_by=auth.user_id,
    )
    db.add(content_item)
    db.flush()

    content_version = ContentVersion(
        content_item_id=content_item.id,
        version_number=1,
        text=body.text,
        text_sha256=hashlib.sha256(body.text.encode("utf-8")).hexdigest(),
        created_by=auth.user_id,
    )
    db.add(content_version)
    db.flush()

    review = start_review(db, content_version, brand.id)
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="review.submitted",
        entity_type="review",
        entity_id=review.id,
        details={"content_item_id": str(content_item.id)},
        request_id=review.request_id,
    )

    db.commit()
    db.refresh(review)
    return ReviewOut.from_model(review)


@router.get("/{review_id}", response_model=ReviewOut)
def get_review(
    review_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ReviewOut:
    review = get_review_or_404(db, auth.organisation_id, review_id)
    return ReviewOut.from_model(review)


@router.post("/{review_id}/rerun", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def rerun_review(
    review_id: uuid.UUID,
    auth: AuthContext = Depends(require_permission(Permission.SUBMIT)),
    db: Session = Depends(get_db),
) -> ReviewOut:
    """Creates and runs a NEW review for the same content_version_id the given review used —
    the old review row is untouched (it stays whatever it was: failed, needs_human_review, ...).
    Useful after a provider failure, or after a brand source changed and the content should be
    re-checked without editing it."""
    old_review = get_review_or_404(db, auth.organisation_id, review_id)
    content_version = db.get(ContentVersion, old_review.content_version_id)
    content_item = db.get(ContentItem, content_version.content_item_id)

    new_review = start_review(db, content_version, content_item.brand_profile_id)
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="review.rerun",
        entity_type="review",
        entity_id=new_review.id,
        details={"rerun_of_review_id": str(old_review.id)},
        request_id=new_review.request_id,
    )

    db.commit()
    db.refresh(new_review)
    return ReviewOut.from_model(new_review)
