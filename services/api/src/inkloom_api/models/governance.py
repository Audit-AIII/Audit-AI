"""Approval decisions and the tenant-wide audit trail.

Governance invariant (docs/backend.md): `if current_version_id != reviewed_version_id: reject
stale approval`. `ApprovalEvent` records both the version acted on and the review it was judged
against, so that check can be made without re-deriving it from other tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..statuses import ApprovalAction, values
from .base import Base, created_at_column, uuid_pk


class ApprovalEvent(Base):
    __tablename__ = "approval_events"
    __table_args__ = (
        CheckConstraint(f"action IN {tuple(values(ApprovalAction))}", name="ck_approval_action"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("content_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id")
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class AuditEvent(Base):
    """Append-only. Every tenant-owned action is logged here, win or lose, approved or rejected."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Structured, safe details only (no secrets, no raw provider errors) — same rule as errors.py.
    details: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(128))
    # Round 3 (migration 0015): which draft this event is about, the version number it applied
    # to, and the person's own note - so a draft's audit history is one indexed query.
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    version_number: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
