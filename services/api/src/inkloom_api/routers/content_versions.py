"""POST /api/content-versions/{id}/approve, POST /api/content-versions/{id}/request-changes
(phase6_versioning_approval_audit.md tasks 4-5).

Individual-user mode: the account owner marks their own content "ready to publish" (approve) or
sends it back (request-changes / reject). Both routes keep their `require_permission(...)`
dependency, which any active membership now satisfies (auth/permissions.py) - so in practice the
only access rule is "this content version is in your own account" (404 otherwise).

`approve` runs every guard in task 4: not yet decidable, stale, or a cited source superseded
since the review ran - all reported as a safe 409. The Phase 9 risk-based routing guard was
removed (no reviewer tiers in a one-person account). `request-changes` only checks that the
review is in a decidable state - staleness and source drift don't matter when the answer is
"no", only when it's "yes".
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..approval_rules import (
    InvalidReviewTransitionError,
    StaleApprovalError,
    SupersededSourceError,
    ensure_decidable,
)
from ..approval_service import check_approve_guards, record_decision
from ..auth.dependencies import AuthContext, require_permission
from ..auth.permissions import Permission
from ..db import get_db
from ..models import Review
from ..request_text import StoredText
from ..schemas import ApprovalEventOut
from ..statuses import ApprovalAction
from ..tenancy import get_content_version_or_404, not_found

router = APIRouter(prefix="/api/content-versions", tags=["content-versions"])


class RequestChangesBody(BaseModel):
    decision: Literal["changes_requested", "rejected"]
    note: StoredText | None = Field(default=None, max_length=2000)


def _latest_review_or_404(db: Session, content_version_id: uuid.UUID) -> Review:
    """Locks the row (`FOR UPDATE`) so two concurrent decisions on the same review serialize:
    the second transaction blocks here until the first commits, then re-reads the now-updated
    status and is correctly rejected by `ensure_decidable` instead of racing it and writing a
    second, contradictory `ApprovalEvent`."""
    review = (
        db.query(Review)
        .filter_by(content_version_id=content_version_id)
        .order_by(Review.created_at.desc())
        .with_for_update()
        .first()
    )
    if review is None:
        raise not_found("no review exists for this content version yet")
    return review


@router.post("/{content_version_id}/approve", response_model=ApprovalEventOut, status_code=201)
def approve_content_version(
    content_version_id: uuid.UUID,
    auth: AuthContext = Depends(require_permission(Permission.APPROVE)),
    db: Session = Depends(get_db),
) -> ApprovalEventOut:
    content_version = get_content_version_or_404(db, auth.organisation_id, content_version_id)
    review = _latest_review_or_404(db, content_version.id)

    try:
        check_approve_guards(db, review, content_version.content_item_id)
    except InvalidReviewTransitionError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    except StaleApprovalError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a newer version of this content exists; this review is stale"
        ) from None
    except SupersededSourceError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a source this review cited is no longer the brand's approved version; rerun the review first",
        ) from None

    event = record_decision(
        db, review, content_version, auth.organisation_id, auth.user_id, ApprovalAction.APPROVED, note=None
    )
    db.commit()
    return ApprovalEventOut.from_model(event, content_version.version_number)


@router.post("/{content_version_id}/request-changes", response_model=ApprovalEventOut, status_code=201)
def request_changes(
    content_version_id: uuid.UUID,
    body: RequestChangesBody,
    auth: AuthContext = Depends(require_permission(Permission.REVIEW)),
    db: Session = Depends(get_db),
) -> ApprovalEventOut:
    content_version = get_content_version_or_404(db, auth.organisation_id, content_version_id)
    review = _latest_review_or_404(db, content_version.id)

    try:
        ensure_decidable(review.status)
    except InvalidReviewTransitionError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None

    action = ApprovalAction.REJECTED if body.decision == "rejected" else ApprovalAction.CHANGES_REQUESTED
    event = record_decision(db, review, content_version, auth.organisation_id, auth.user_id, action, body.note)
    db.commit()
    return ApprovalEventOut.from_model(event, content_version.version_number)
