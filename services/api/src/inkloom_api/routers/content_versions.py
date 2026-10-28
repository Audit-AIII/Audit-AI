"""POST /api/content-versions/{id}/approve, POST /api/content-versions/{id}/request-changes.

Who may decide (auth/permissions.py): approve and reject need an approver or owner; sending back
(`changes_requested`) also a reviewer. A content version outside the caller's workspace is a 404.

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
from inkloom_verify.intent_lock import IntentLockError, validate_locks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..approval_rules import (
    InvalidReviewTransitionError,
    StaleApprovalError,
    SupersededSourceError,
    ensure_decidable,
)
from ..approval_service import check_approve_guards, record_decision
from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..db import get_db
from ..models import ContentItem, Review
from ..request_text import NUL, StoredText
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
        db,
        review,
        content_version,
        auth.organisation_id,
        auth.user_id,
        ApprovalAction.APPROVED,
        note=None,
    )
    db.commit()
    return ApprovalEventOut.from_model(event, content_version.version_number)


@router.post(
    "/{content_version_id}/request-changes", response_model=ApprovalEventOut, status_code=201
)
def request_changes(
    content_version_id: uuid.UUID,
    body: RequestChangesBody,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ApprovalEventOut:
    # Rejecting is a final "no" (approvers); sending back for changes is also a reviewer's call.
    auth.require(Permission.REJECT if body.decision == "rejected" else Permission.REQUEST_CHANGES)
    content_version = get_content_version_or_404(db, auth.organisation_id, content_version_id)
    review = _latest_review_or_404(db, content_version.id)

    try:
        ensure_decidable(review.status)
    except InvalidReviewTransitionError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None

    action = (
        ApprovalAction.REJECTED if body.decision == "rejected" else ApprovalAction.CHANGES_REQUESTED
    )
    event = record_decision(
        db, review, content_version, auth.organisation_id, auth.user_id, action, body.note
    )
    db.commit()
    return ApprovalEventOut.from_model(event, content_version.version_number)


# --- Intent-lock (Phase 7) ---------------------------------------------------------------------


class LocksBody(BaseModel):
    locked_phrases: list[str]


class LocksOut(BaseModel):
    content_version_id: uuid.UUID
    locked_phrases: list[str]


@router.get("/{content_version_id}/locks", response_model=LocksOut)
def get_locks(
    content_version_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> LocksOut:
    version = get_content_version_or_404(db, auth.organisation_id, content_version_id)
    return LocksOut(
        content_version_id=version.id, locked_phrases=list(version.locked_phrases or [])
    )


@router.put("/{content_version_id}/locks", response_model=LocksOut)
def put_locks(
    content_version_id: uuid.UUID,
    body: LocksBody,
    auth: AuthContext = Depends(require_permission(Permission.EDIT_CONTENT)),
    db: Session = Depends(get_db),
) -> LocksOut:
    """The writer's must-keep phrases for this version (exact, case-sensitive; the engine's
    `validate_locks` rules: at most 50, each 1-200 characters, duplicates dropped). Replaces the
    list. Reviews that run afterwards never get a suggestion that removes one, and a stored
    suggestion that would is withheld when read (`withheld_by_intent_lock`)."""
    version = get_content_version_or_404(db, auth.organisation_id, content_version_id)
    # A writer sets locks only on their own drafts.
    auth.require(Permission.EDIT_CONTENT, db.get(ContentItem, version.content_item_id))
    if any(NUL in phrase for phrase in body.locked_phrases):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "locked phrases must not contain NUL (0x00) characters",
        )
    try:
        locks = validate_locks(body.locked_phrases)
    except IntentLockError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from None
    version.locked_phrases = locks
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="content_version.locks_updated",
        entity_type="content_version",
        entity_id=version.id,
        details={"count": len(locks)},  # never the phrases themselves
    )
    db.commit()
    return LocksOut(content_version_id=version.id, locked_phrases=locks)
