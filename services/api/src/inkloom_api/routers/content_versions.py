"""POST /api/content-versions/{id}/approve, .../request-changes, .../publish (and Intent-lock).

Who may decide (auth/permissions.py): approve, reject and publish need an approver or owner;
sending back (`changes_requested`) also a reviewer. A content version outside the caller's
workspace is a 404.

Every decision runs, in order, inside one transaction with the draft and its latest review
row-locked:
1. the role (403 FORBIDDEN);
2. approve only: the author can't approve their own work unless nobody else could (403
   SELF_APPROVAL_FORBIDDEN, decision D1);
3. the workflow (workflow.check_decision): a draft that needs a reviewer can't be approved yet
   (409 REVIEW_REQUIRED), the person who reviewed it doesn't approve it (403
   SAME_REVIEWER_APPROVER_FORBIDDEN), other states are 409 INVALID_TRANSITION, an older version
   is 409 CONFLICT;
4. the review's own guards from task 4: not yet decidable, or (approve) a cited source superseded
   since it ran - 409 CONFLICT;
5. a decision on a `draft` submits it first (D4), then the decision is recorded.

A refused approve or publish leaves the draft exactly as it was and writes one `approval_denied`
audit event (workflow.deny).
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from inkloom_verify.intent_lock import IntentLockError, validate_locks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import workflow
from ..approval_rules import (
    InvalidReviewTransitionError,
    StaleApprovalError,
    SupersededSourceError,
    ensure_decidable,
)
from ..approval_service import (
    SelfApprovalForbiddenError,
    check_approve_guards,
    check_not_self_approval,
    record_decision,
)
from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..db import get_db
from ..errors import ApiException, ErrorCode
from ..models import ContentItem, Review
from ..request_text import NUL, StoredText
from ..schemas import ApprovalEventOut, WorkflowActionOut
from ..statuses import ApprovalAction
from ..tenancy import get_content_version_or_404, not_found

router = APIRouter(prefix="/api/content-versions", tags=["content-versions"])

# Refusals of these are recorded as `approval_denied` (Phases 3-4): an attempt to approve or
# publish something the rules don't allow is worth keeping in the audit trail.
_DENIAL_CODES = frozenset(
    {
        ErrorCode.SELF_APPROVAL_FORBIDDEN,
        ErrorCode.REVIEW_REQUIRED,
        ErrorCode.SAME_REVIEWER_APPROVER_FORBIDDEN,
    }
)


class RequestChangesBody(BaseModel):
    decision: Literal["changes_requested", "rejected"]
    note: StoredText | None = Field(default=None, max_length=2000)


def _latest_review_or_404(db: Session, content_version_id: uuid.UUID) -> Review:
    """Locks the row (`FOR UPDATE`) so two concurrent decisions on the same review serialize:
    the second transaction blocks here until the first commits, then re-reads the now-updated
    status and is correctly rejected by `ensure_decidable` instead of racing it and writing a
    second, contradictory `ApprovalEvent`."""
    review = workflow.latest_review(db, content_version_id, lock=True)
    if review is None:
        raise not_found("no review exists for this content version yet")
    return review


def _decide(
    db: Session,
    auth: AuthContext,
    content_version_id: uuid.UUID,
    action: ApprovalAction,
    note: str | None,
) -> ApprovalEventOut:
    content_version = get_content_version_or_404(db, auth.organisation_id, content_version_id)
    review = _latest_review_or_404(db, content_version.id)
    item = workflow.lock_item(db, content_version.content_item_id)
    item_id = item.id

    self_approval = False
    if action is ApprovalAction.APPROVED:
        try:
            self_approval = check_not_self_approval(
                db, auth.organisation_id, auth.user_id, item, content_version
            )
        except SelfApprovalForbiddenError:
            workflow.deny(
                db, auth, item_id, content_version, workflow.self_approval_error(), "approve"
            )
    try:
        # The review itself first, with the answers this route has always given (409 CONFLICT
        # "cannot decide a review in status ..."); then the draft's workflow state.
        ensure_decidable(review.status)
        plan = workflow.check_decision(db, auth, item, content_version, review, action.value)
        if action is ApprovalAction.APPROVED:
            check_approve_guards(db, review, content_version.content_item_id)
    except ApiException as error:
        if action is ApprovalAction.APPROVED and error.code in _DENIAL_CODES:
            workflow.deny(db, auth, item_id, content_version, error, "approve")
        raise
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

    before = item.workflow_status
    if plan.implicit_submit:
        workflow.submit(db, auth, item, content_version, review, implicit=True)
    if plan.solo_review:
        workflow.solo_review(db, auth, item, content_version, review)
    after = workflow.finish_decision(item, action.value)
    event = record_decision(
        db,
        review,
        content_version,
        auth.organisation_id,
        auth.user_id,
        action,
        note=note,
        self_approval=self_approval,
        workflow_before=before,
        workflow_after=after.value,
    )
    db.commit()
    return ApprovalEventOut.from_model(event, content_version.version_number)


@router.post("/{content_version_id}/approve", response_model=ApprovalEventOut, status_code=201)
def approve_content_version(
    content_version_id: uuid.UUID,
    auth: AuthContext = Depends(require_permission(Permission.APPROVE)),
    db: Session = Depends(get_db),
) -> ApprovalEventOut:
    return _decide(db, auth, content_version_id, ApprovalAction.APPROVED, None)


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
    action = (
        ApprovalAction.REJECTED if body.decision == "rejected" else ApprovalAction.CHANGES_REQUESTED
    )
    return _decide(db, auth, content_version_id, action, body.note)


@router.post("/{content_version_id}/publish", response_model=WorkflowActionOut)
def publish_content_version(
    content_version_id: uuid.UUID,
    auth: AuthContext = Depends(require_permission(Permission.PUBLISH)),
    db: Session = Depends(get_db),
) -> WorkflowActionOut:
    """approved -> published. Refused (and recorded as `approval_denied`) when the content still
    needs its review, or the caller wrote it and someone else could publish it."""
    content_version = get_content_version_or_404(db, auth.organisation_id, content_version_id)
    item = workflow.lock_item(db, content_version.content_item_id)
    item_id = item.id
    try:
        workflow.publish(db, auth, item, content_version)
    except ApiException as error:
        if error.code in _DENIAL_CODES:
            workflow.deny(db, auth, item_id, content_version, error, "publish")
        raise
    db.commit()
    return WorkflowActionOut.from_item(item, content_version.version_number)


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
