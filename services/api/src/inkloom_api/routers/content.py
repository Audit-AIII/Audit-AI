"""POST /api/content/{id}/versions, GET /api/content/{id}/history, and the Round 3 workflow
actions on a draft: POST /api/content/{id}/submit, /assign, /mark-reviewed (workflow.py).

Creating a version also runs a review on it synchronously (confirmed with the team) — one call,
one result, same pattern as `POST /api/reviews`.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, Query
from inkloom_verify.intent_lock import intent_lock_violations
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit_history, workflow
from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..db import get_db
from ..models import ApprovalEvent, ContentVersion, Finding, FindingComment, FindingDecision, Review
from ..request_text import StoredText
from ..review_queries import review_out
from ..review_runner import start_review
from ..schemas import (
    ApprovalEventOut,
    AuditEventOut,
    AuditHistoryOut,
    ContentHistoryOut,
    ContentVersionHistoryOut,
    FindingEventOut,
    LockWarningOut,
    NewVersionResponse,
    ReviewSummaryOut,
    WorkflowActionOut,
)
from ..tenancy import get_content_item_or_404, not_found

router = APIRouter(prefix="/api/content", tags=["content"])

MAX_CONTENT_CHARS = 100_000  # matches inkloom_verify.schemas.MAX_CONTENT_CHARS


class NewVersionRequest(BaseModel):
    text: StoredText = Field(min_length=1, max_length=MAX_CONTENT_CHARS)


@router.post("/{content_item_id}/versions", response_model=NewVersionResponse, status_code=201)
def create_version(
    content_item_id: uuid.UUID,
    body: NewVersionRequest,
    auth: AuthContext = Depends(require_permission(Permission.EDIT_CONTENT)),
    db: Session = Depends(get_db),
) -> NewVersionResponse:
    item = get_content_item_or_404(db, auth.organisation_id, content_item_id)
    auth.require(Permission.EDIT_CONTENT, item)  # a writer edits only their own drafts

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
        # The writer's Intent-lock list carries over to the edit; change it with PUT .../locks.
        locked_phrases=list(previous_current.locked_phrases or [])
        if previous_current is not None
        else [],
    )
    db.add(new_version)
    db.flush()

    review = start_review(db, new_version, item.brand_profile_id)
    workflow.on_new_version(item)
    workflow.on_review_finished(db, item, review, auth.user_id)
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
    warnings = (
        intent_lock_violations(
            previous_current.text, new_version.text, previous_current.locked_phrases or []
        )
        if previous_current is not None
        else []
    )
    return NewVersionResponse(
        content_version_id=new_version.id,
        version_number=new_version.version_number,
        is_current=new_version.is_current,
        review=review_out(db, auth, review),
        lock_warnings=[LockWarningOut(**w.model_dump()) for w in warnings],
    )


def _finding_events(db: Session, review_ids: list[uuid.UUID]) -> list[FindingEventOut]:
    """Dismiss / restore / comment on the findings of these reviews, oldest first. Never the
    comment text."""
    if not review_ids:
        return []
    decisions = (
        db.query(FindingDecision)
        .join(Finding, Finding.finding_id == FindingDecision.finding_id)
        .filter(Finding.review_id.in_(review_ids))
        .all()
    )
    comments = (
        db.query(FindingComment)
        .join(Finding, Finding.finding_id == FindingComment.finding_id)
        .filter(Finding.review_id.in_(review_ids))
        .all()
    )
    events = [
        FindingEventOut(
            event_type=f"finding.{d.action}",
            finding_id=d.finding_id,
            actor_user_id=d.actor_user_id,
            created_at=d.created_at,
            note=d.note,
        )
        for d in decisions
    ] + [
        FindingEventOut(
            event_type="finding.commented",
            finding_id=c.finding_id,
            actor_user_id=c.author_user_id,
            created_at=c.created_at,
            note=None,
        )
        for c in comments
    ]
    return sorted(events, key=lambda e: e.created_at)


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
        reviews = (
            db.query(Review)
            .filter_by(content_version_id=version.id)
            .order_by(Review.created_at)
            .all()
        )
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
                decisions=[
                    ApprovalEventOut.from_model(d, version.version_number) for d in decisions
                ],
                finding_events=_finding_events(db, [r.id for r in reviews]),
            )
        )

    return ContentHistoryOut(content_item_id=item.id, title=item.title, versions=history)


# --- Round 3 workflow (docs/governance.md section 6) ------------------------------------------


class SubmitBody(BaseModel):
    content_version_id: uuid.UUID  # the version the caller saw: an older one is 409 CONFLICT


class AssignBody(BaseModel):
    reviewer_user_id: uuid.UUID | None  # null unassigns


class MarkReviewedBody(BaseModel):
    content_version_id: uuid.UUID
    note: StoredText | None = Field(default=None, max_length=2000)


def _locked_version(db: Session, auth: AuthContext, content_item_id, content_version_id):
    item = get_content_item_or_404(db, auth.organisation_id, content_item_id)
    version = db.get(ContentVersion, content_version_id)
    if version is None or version.content_item_id != item.id:
        raise not_found("content version not found")
    review = workflow.latest_review(db, version.id, lock=True)
    if review is None:
        raise not_found("no review exists for this content version yet")
    return workflow.lock_item(db, item.id), version, review


@router.post("/{content_item_id}/submit", response_model=WorkflowActionOut)
def submit_draft(
    content_item_id: uuid.UUID,
    body: SubmitBody,
    auth: AuthContext = Depends(require_permission(Permission.SUBMIT)),
    db: Session = Depends(get_db),
) -> WorkflowActionOut:
    """draft -> in_review (the findings need a reviewer) or submitted (clean: approver only).
    The routing decision and its reason are stored on the draft and in the audit trail."""
    item, version, review = _locked_version(db, auth, content_item_id, body.content_version_id)
    auth.require(Permission.SUBMIT, item)  # a writer submits only their own drafts
    workflow.submit(db, auth, item, version, review)
    db.commit()
    return WorkflowActionOut.from_item(item, version.version_number)


@router.post("/{content_item_id}/assign", response_model=WorkflowActionOut)
def assign_reviewer(
    content_item_id: uuid.UUID,
    body: AssignBody,
    auth: AuthContext = Depends(require_permission(Permission.ASSIGN)),
    db: Session = Depends(get_db),
) -> WorkflowActionOut:
    item = get_content_item_or_404(db, auth.organisation_id, content_item_id)
    item = workflow.lock_item(db, item.id)
    workflow.assign(db, auth, item, body.reviewer_user_id)
    db.commit()
    db.refresh(item)
    return WorkflowActionOut.from_item(item, workflow.current_version(db, item).version_number)


@router.post("/{content_item_id}/mark-reviewed", response_model=WorkflowActionOut)
def mark_reviewed(
    content_item_id: uuid.UUID,
    body: MarkReviewedBody,
    auth: AuthContext = Depends(require_permission(Permission.MARK_REVIEWED)),
    db: Session = Depends(get_db),
) -> WorkflowActionOut:
    """in_review -> reviewed. Not by the draft's author, unless nobody else could (D6)."""
    item, version, review = _locked_version(db, auth, content_item_id, body.content_version_id)
    workflow.mark_reviewed(db, auth, item, version, review, body.note)
    db.commit()
    return WorkflowActionOut.from_item(item, version.version_number)


@router.get("/{content_item_id}/audit", response_model=AuditHistoryOut)
def get_audit_history(
    content_item_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=500),
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> AuditHistoryOut:
    """The draft's audit trail, newest first: who did what, to which version, when, and why.
    Any member of the workspace may read it; another workspace's draft is a 404."""
    item = get_content_item_or_404(db, auth.organisation_id, content_item_id)
    events, next_cursor, numbers = audit_history.draft_history(db, item, cursor, limit)
    people = audit_history.actors(db, events)
    return AuditHistoryOut(
        content_item_id=item.id,
        items=[
            AuditEventOut.from_model(e, people.get(e.actor_user_id), numbers.get(e.entity_id))
            for e in events
        ],
        next_cursor=next_cursor,
    )
