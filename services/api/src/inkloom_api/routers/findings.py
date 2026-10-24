"""Per-finding Dismiss / restore and comments on findings (Phase 7; DESIGN.md §21 `Decision`,
services/verification/HANDOFF_STEPS_6_8.md "Per-finding Dismiss" and "Comments on findings").

A decision is a separate `FindingDecision` row plus an audit event: the finding itself - its
verification_status, evidence and explanation - is never changed, and a dismissed finding is not
"supported" (a contradicted finding stays contradicted in the record). Dismissing does not change
the review's status either. A finding in another account is a 404 identical to a random id.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..db import get_db
from ..models import Finding, FindingComment, FindingDecision
from ..request_text import StoredText
from ..tenancy import get_review_or_404, not_found

router = APIRouter(prefix="/api/findings", tags=["findings"])


class DecisionBody(BaseModel):
    note: StoredText | None = Field(default=None, max_length=2000)


class CommentBody(BaseModel):
    body: StoredText = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("comment must not be blank")
        return value


class FindingDecisionOut(BaseModel):
    id: uuid.UUID
    finding_id: uuid.UUID
    action: str  # "dismissed" | "restored"
    note: str | None
    actor_user_id: uuid.UUID | None
    created_at: datetime


class FindingCommentOut(BaseModel):
    id: uuid.UUID
    finding_id: uuid.UUID
    author_user_id: uuid.UUID | None
    body: str
    created_at: datetime


def _finding_or_404(
    db: Session, auth: AuthContext, finding_id: uuid.UUID, lock: bool = False
) -> Finding:
    """Scoped through the finding's review (tenancy.get_review_or_404). `lock` takes a row lock so
    two concurrent decisions on one finding serialize instead of both being recorded."""
    finding = db.get(Finding, finding_id, with_for_update=lock)
    if finding is None:
        raise not_found("finding not found")
    try:
        get_review_or_404(db, auth.organisation_id, finding.review_id)
    except HTTPException:
        raise not_found("finding not found") from None  # same as a random id
    return finding


def _is_dismissed(db: Session, finding_id: uuid.UUID) -> bool:
    latest = (
        db.query(FindingDecision.action)
        .filter_by(finding_id=finding_id)
        .order_by(FindingDecision.created_at.desc(), FindingDecision.id.desc())
        .first()
    )
    return latest is not None and latest.action == "dismissed"


def _decide(
    db: Session, auth: AuthContext, finding_id: uuid.UUID, action: str, note: str | None
) -> FindingDecisionOut:
    finding = _finding_or_404(db, auth, finding_id, lock=True)
    dismissed = _is_dismissed(db, finding.finding_id)
    if action == "dismissed" and dismissed:
        raise HTTPException(status.HTTP_409_CONFLICT, "this finding is already dismissed")
    if action == "restored" and not dismissed:
        raise HTTPException(status.HTTP_409_CONFLICT, "this finding is not dismissed")
    decision = FindingDecision(
        finding_id=finding.finding_id, action=action, note=note, actor_user_id=auth.user_id
    )
    db.add(decision)
    db.flush()
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type=f"finding.{action}",
        entity_type="finding",
        entity_id=finding.finding_id,
        details={"review_id": str(finding.review_id), **({"note": note} if note else {})},
    )
    db.commit()
    db.refresh(decision)
    return FindingDecisionOut(
        id=decision.id,
        finding_id=decision.finding_id,
        action=decision.action,
        note=decision.note,
        actor_user_id=decision.actor_user_id,
        created_at=decision.created_at,
    )


@router.post(
    "/{finding_id}/dismiss", response_model=FindingDecisionOut, status_code=status.HTTP_201_CREATED
)
def dismiss_finding(
    finding_id: uuid.UUID,
    body: DecisionBody | None = None,
    auth: AuthContext = Depends(require_permission(Permission.REVIEW)),
    db: Session = Depends(get_db),
) -> FindingDecisionOut:
    return _decide(db, auth, finding_id, "dismissed", body.note if body else None)


@router.post(
    "/{finding_id}/restore", response_model=FindingDecisionOut, status_code=status.HTTP_201_CREATED
)
def restore_finding(
    finding_id: uuid.UUID,
    body: DecisionBody | None = None,
    auth: AuthContext = Depends(require_permission(Permission.REVIEW)),
    db: Session = Depends(get_db),
) -> FindingDecisionOut:
    return _decide(db, auth, finding_id, "restored", body.note if body else None)


@router.get("/{finding_id}/comments", response_model=list[FindingCommentOut])
def list_comments(
    finding_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[FindingCommentOut]:
    finding = _finding_or_404(db, auth, finding_id)
    comments = (
        db.query(FindingComment)
        .filter_by(finding_id=finding.finding_id)
        .order_by(FindingComment.created_at, FindingComment.id)
        .all()
    )
    return [
        FindingCommentOut(
            id=c.id,
            finding_id=c.finding_id,
            author_user_id=c.author_user_id,
            body=c.body,
            created_at=c.created_at,
        )
        for c in comments
    ]


@router.post(
    "/{finding_id}/comments", response_model=FindingCommentOut, status_code=status.HTTP_201_CREATED
)
def add_comment(
    finding_id: uuid.UUID,
    body: CommentBody,
    auth: AuthContext = Depends(require_permission(Permission.REVIEW)),
    db: Session = Depends(get_db),
) -> FindingCommentOut:
    finding = _finding_or_404(db, auth, finding_id)
    comment = FindingComment(
        finding_id=finding.finding_id, author_user_id=auth.user_id, body=body.body
    )
    db.add(comment)
    db.flush()
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="finding.commented",
        entity_type="finding",
        entity_id=finding.finding_id,
        details={
            "review_id": str(finding.review_id),
            "comment_id": str(comment.id),
        },  # never the text
    )
    db.commit()
    db.refresh(comment)
    return FindingCommentOut(
        id=comment.id,
        finding_id=comment.finding_id,
        author_user_id=comment.author_user_id,
        body=comment.body,
        created_at=comment.created_at,
    )
