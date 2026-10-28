"""Reading the audit trail (Round 3 Phase 5, docs/governance.md 9.3).

`audit_events` is append-only (migration 0016 refuses UPDATE) and workspace-scoped; this module
only reads it. A draft's history is every event about it: Round 3 events carry
`content_item_id`, and older ones are matched through the draft's versions, reviews and findings
(`entity_type` / `entity_id`), so drafts from before Round 3 show their full history too.

Each event gets a stable `action` name for the frontend. Round 3 events already use one; older
event types are mapped (`content_version.approved` -> `approval_granted`, ...). The raw
`event_type` is always returned alongside, and an event type this module doesn't know is passed
through as its own action - never dropped.

Pagination is by an opaque cursor (the last item's `created_at` and `id`), newest first, so a new
event arriving between two pages never shifts or repeats items.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .models import AuditEvent, ContentItem, ContentVersion, Finding, Review, User

LEGACY_ACTIONS = {
    "review.submitted": "draft_created",
    "content_version.created": "version_created",
    "review.rerun": "recheck_requested",
    "content_version.approved": "approval_granted",
    "content_version.rejected": "approval_rejected",
    "content_version.changes_requested": "changes_requested",
    "content_version.source_changed": "source_changed",
    "content_version.locks_updated": "locks_updated",
    "finding.dismissed": "finding_dismissed",
    "finding.restored": "finding_restored",
    "finding.commented": "finding_commented",
    "evidence.integrity_rejected": "evidence_rejected",
}


def action_for(event_type: str) -> str:
    return LEGACY_ACTIONS.get(event_type, event_type)


def encode_cursor(event: AuditEvent) -> str:
    raw = json.dumps({"t": event.created_at.isoformat(), "i": str(event.id)})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid cursor") from None


def _page(query, cursor: str | None, limit: int) -> tuple[list[AuditEvent], str | None]:
    if cursor:
        at, event_id = decode_cursor(cursor)
        query = query.filter(
            or_(
                AuditEvent.created_at < at,
                and_(AuditEvent.created_at == at, AuditEvent.id < event_id),
            )
        )
    rows = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, (encode_cursor(rows[-1]) if more and rows else None)


def draft_history(
    db: Session, item: ContentItem, cursor: str | None, limit: int
) -> tuple[list[AuditEvent], str | None, dict[str, int]]:
    """Events about one draft, newest first. Also returns {entity id: version_number} for the
    older events that don't carry their version number themselves."""
    versions = db.query(ContentVersion.id, ContentVersion.version_number).filter_by(
        content_item_id=item.id
    )
    version_of = {str(v_id): number for v_id, number in versions}
    reviews = db.query(Review.id, Review.content_version_id).filter(
        Review.content_version_id.in_([uuid.UUID(v) for v in version_of])
    )
    review_version = {str(r_id): version_of[str(v_id)] for r_id, v_id in reviews}
    findings = db.query(Finding.finding_id, Finding.review_id).filter(
        Finding.review_id.in_([uuid.UUID(r) for r in review_version])
    )
    finding_version = {str(f_id): review_version[str(r_id)] for f_id, r_id in findings}
    numbers = {**version_of, **review_version, **finding_version}

    query = db.query(AuditEvent).filter(
        AuditEvent.organisation_id == item.organisation_id,
        or_(
            AuditEvent.content_item_id == item.id,
            and_(
                AuditEvent.entity_type == "content_version",
                AuditEvent.entity_id.in_(list(version_of)),
            ),
            and_(
                AuditEvent.entity_type == "review", AuditEvent.entity_id.in_(list(review_version))
            ),
            and_(
                AuditEvent.entity_type == "finding", AuditEvent.entity_id.in_(list(finding_version))
            ),
        ),
    )
    rows, next_cursor = _page(query, cursor, limit)
    return rows, next_cursor, numbers


WORKSPACE_EVENT_TYPES = (
    "account.registered",
    "invite_created",
    "invite_accepted",
    "invite_revoked",
    "member_role_changed",
    "member_removed",
)


def workspace_history(
    db: Session, organisation_id: uuid.UUID, cursor: str | None, limit: int
) -> tuple[list[AuditEvent], str | None]:
    """Membership and invitation events of one workspace, newest first."""
    query = db.query(AuditEvent).filter(
        AuditEvent.organisation_id == organisation_id,
        AuditEvent.event_type.in_(WORKSPACE_EVENT_TYPES),
    )
    return _page(query, cursor, limit)


def actors(db: Session, events: list[AuditEvent]) -> dict[uuid.UUID, User]:
    ids = {e.actor_user_id for e in events if e.actor_user_id is not None}
    return {u.id: u for u in db.query(User).filter(User.id.in_(ids))} if ids else {}
