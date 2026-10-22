"""Declarative base and shared column helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk(name: str = "id") -> Mapped[uuid.UUID]:
    return mapped_column(name, UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
