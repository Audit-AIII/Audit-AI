"""DB-aware half of Phase 6 approval: the guards task 4 lists, and applying a decision.

`approval_rules.py` is the pure state machine; this module is where those checks meet the
database. Kept separate so the state machine stays trivially unit-testable.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .approval_rules import SupersededSourceError, ensure_decidable, ensure_not_stale
from .models import (
    ApprovalEvent,
    AuditEvent,
    BrandSource,
    ContentVersion,
    EvidenceLink,
    Finding,
    Review,
    SourceVersion,
)
from .statuses import ApprovalAction, BrandSourceStatus, ReviewState


def current_version_id(db: Session, content_item_id: uuid.UUID) -> uuid.UUID:
    version = (
        db.query(ContentVersion).filter_by(content_item_id=content_item_id, is_current=True).one()
    )
    return version.id


def check_approve_guards(db: Session, review: Review, content_item_id: uuid.UUID) -> None:
    """Raises on the first guard that fails (task 4): not yet decidable, stale, or a cited source
    no longer the brand's approved one. The acting user's role is deliberately not an input any
    more (individual-user mode: the account owner approves their own content; see
    approval_rules.py). Never called for reject/request-changes - those are always safe to record
    regardless of staleness or source drift."""
    ensure_decidable(review.status)
    ensure_not_stale(review.content_version_id, current_version_id(db, content_item_id))
    _check_sources_not_superseded(db, review)


def _check_sources_not_superseded(db: Session, review: Review) -> None:
    cited = (
        db.query(EvidenceLink.source_id, EvidenceLink.source_version_id)
        .join(Finding, Finding.finding_id == EvidenceLink.finding_id)
        .filter(Finding.review_id == review.id, EvidenceLink.source_id.isnot(None))
        .distinct()
        .all()
    )
    for source_id, source_version_id in cited:
        source = db.get(BrandSource, source_id)
        if source is None or source.status != BrandSourceStatus.APPROVED.value:
            raise SupersededSourceError(str(source_id))
        latest = (
            db.query(SourceVersion)
            .filter_by(brand_source_id=source_id)
            .order_by(SourceVersion.version_number.desc())
            .first()
        )
        if latest is None or latest.id != source_version_id:
            raise SupersededSourceError(str(source_id))


_STATE_FOR_ACTION = {
    ApprovalAction.APPROVED: ReviewState.APPROVED,
    ApprovalAction.REJECTED: ReviewState.REJECTED,
    ApprovalAction.CHANGES_REQUESTED: ReviewState.CHANGES_REQUESTED,
}


def record_decision(
    db: Session,
    review: Review,
    content_version: ContentVersion,
    organisation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    action: ApprovalAction,
    note: str | None,
) -> ApprovalEvent:
    """Applies the decision: updates the review's status, records the `ApprovalEvent`, and logs
    an `AuditEvent` - in the same session/transaction as the caller (task 7: "write the state
    change and its audit event in the same transaction where feasible")."""
    event = ApprovalEvent(
        content_version_id=content_version.id,
        review_id=review.id,
        action=action.value,
        actor_user_id=actor_user_id,
        note=note,
    )
    db.add(event)
    review.status = _STATE_FOR_ACTION[action].value
    db.add(
        AuditEvent(
            organisation_id=organisation_id,
            actor_user_id=actor_user_id,
            event_type=f"content_version.{action.value}",
            entity_type="content_version",
            entity_id=str(content_version.id),
            details={"review_id": str(review.id), "note": note}
            if note
            else {"review_id": str(review.id)},
            request_id=review.request_id,
        )
    )
    return event
