"""One place to write an audit event (phase6 task 7: "submit, source approval, review, edit,
request changes, approve, reject and retries"). `details` must stay structured and safe — no
content text, no provider errors, no secrets (same rule as errors.py)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .models import AuditEvent


def log_audit_event(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    event_type: str,
    entity_type: str,
    entity_id: object,
    details: dict | None = None,
    request_id: str | None = None,
    content_item_id: uuid.UUID | None = None,
    version_number: int | None = None,
    note: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            organisation_id=organisation_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
            request_id=request_id,
            content_item_id=content_item_id,
            version_number=version_number,
            note=note,
        )
    )
