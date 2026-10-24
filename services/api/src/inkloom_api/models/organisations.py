"""Organisations, users and memberships. Every tenant-owned record resolves to an organisation
either directly (this file) or by following a foreign key to a table that does."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..statuses import MembershipRole, values
from .base import Base, created_at_column, updated_at_column, uuid_pk


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    # passive_deletes=True: organisation_id is NOT NULL with ON DELETE CASCADE at the DB level.
    # Without this, SQLAlchemy's default behaviour when a loaded `memberships` collection's
    # parent is deleted is to try to null out each child's FK itself (it doesn't delete, since
    # no cascade="delete" is set) - which fails the NOT NULL constraint instead of letting
    # Postgres's own CASCADE handle it.
    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organisation", passive_deletes=True
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    # Nullable: Phase 2 decides the auth mechanism (password, magic link, OAuth). Never store a
    # plaintext password; this column holds a hash only, chosen in Phase 2.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", passive_deletes=True
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organisation_id", "user_id", name="uq_membership_org_user"),
        CheckConstraint(f"role IN {tuple(values(MembershipRole))}", name="ck_membership_role"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    organisation: Mapped[Organisation] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
