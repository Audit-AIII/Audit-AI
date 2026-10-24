"""Content submitted for review, and its immutable versions.

`ContentVersion` is never updated after creation: a correction creates a new version instead
(see `POST /api/content/{id}/versions` in 00_CONTEXT.md's route map). This is what lets an
approval be checked against a specific version and rejected as stale if the content has moved on
(governance invariant: `current_version_id != reviewed_version_id`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, created_at_column, updated_at_column, uuid_pk


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Phase 6: which brand's sources every version of this content is checked against. Set once
    # at creation (routers/reviews.py); nullable only because rows from before this column
    # existed have no value, never for a newly created content item.
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    versions: Mapped[list["ContentVersion"]] = relationship(back_populates="content_item", passive_deletes=True)
    # Read-only: lets ReviewOut.from_model show the brand's name without another query.
    brand_profile: Mapped["BrandProfile | None"] = relationship("BrandProfile", viewonly=True)


class ContentVersion(Base):
    """The text is immutable: no `updated_at`. `text_sha256` names match
    `inkloom_verify.schemas.InputContent` (CONTRACTS.md, "Text hashes"). `locked_phrases` (the
    writer's Intent-lock list, migration 0012) is the one field that can change after creation."""

    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint("content_item_id", "version_number", name="uq_content_version_number"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    content_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Phase 6 / Member 1 wiring: exactly one version per content item is current at a time.
    # Creating a new version flips the previous one to False in the same transaction. This is
    # what "the old approval becomes historical only" means at the data level.
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Intent-lock: exact must-keep phrases (validated by inkloom_verify.intent_lock.validate_locks).
    # No suggestion that would remove one is ever offered (intent_lock_guard.py).
    locked_phrases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()

    content_item: Mapped[ContentItem] = relationship(back_populates="versions")
