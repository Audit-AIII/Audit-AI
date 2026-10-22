"""Brand knowledge: profiles, sources and the immutable text of each source version.

A `BrandSource` resolves to an organisation via `brand_profile_id -> brand_profiles.organisation_id`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..statuses import BrandSourceSensitivity, BrandSourceStatus, SourceFileType, values
from .base import Base, created_at_column, updated_at_column, uuid_pk


class BrandProfile(Base):
    __tablename__ = "brand_profiles"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_brand_profile_org_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    # passive_deletes=True: see organisations.py for why - without it, deleting a BrandProfile
    # while its `sources` collection is loaded would try to null out brand_sources.brand_profile_id
    # (NOT NULL) itself instead of letting the DB's ON DELETE CASCADE handle it.
    sources: Mapped[list["BrandSource"]] = relationship(back_populates="brand_profile", passive_deletes=True)


class BrandSource(Base):
    __tablename__ = "brand_sources"
    __table_args__ = (
        CheckConstraint(f"status IN {tuple(values(BrandSourceStatus))}", name="ck_brand_source_status"),
        CheckConstraint(
            f"sensitivity IN {tuple(values(BrandSourceSensitivity))}", name="ck_brand_source_sensitivity"
        ),
        CheckConstraint(f"source_type IN {tuple(values(SourceFileType))}", name="ck_brand_source_file_type"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BrandSourceStatus.DRAFT.value)
    sensitivity: Mapped[str] = mapped_column(
        String(20), nullable=False, default=BrandSourceSensitivity.NORMAL.value
    )
    # Phase 4: what kind of file this source was uploaded as, and where the original bytes live
    # on disk (outside any public path - see config.py's brand_source_storage_dir). Both
    # nullable: a source created another way (e.g. the seed script) has neither.
    source_type: Mapped[str | None] = mapped_column(String(10))
    storage_path: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    brand_profile: Mapped[BrandProfile] = relationship(back_populates="sources")
    versions: Mapped[list["SourceVersion"]] = relationship(back_populates="brand_source", passive_deletes=True)


class SourceVersion(Base):
    """One immutable snapshot of a brand source's text. `text_sha256` names match
    `inkloom_verify.schemas.ReferenceDocument` so the same text produces the same hash on both
    sides of the engine boundary (CONTRACTS.md, "Text hashes")."""

    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint("brand_source_id", "version_number", name="uq_source_version_number"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    brand_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()

    brand_source: Mapped[BrandSource] = relationship(back_populates="versions")
