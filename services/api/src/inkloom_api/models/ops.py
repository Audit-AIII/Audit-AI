"""Operational tables: provider call log, idempotency and result caching (Phase 5 uses these;
the schema is created now so later phases don't need a migration just to add a table).

None of these store prompts, raw provider responses or document text — only metadata needed for
auditing cost/latency and for safely replaying a request. `result_cache.report` is the one
exception: it holds a full `VerificationReport`, which is exactly what `GET /api/reviews/{id}`
would return anyway, scoped per-tenant like every other table here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..statuses import ExternalCallStatus, values
from .base import Base, created_at_column, uuid_pk


class ExternalCallLog(Base):
    __tablename__ = "external_call_log"
    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(values(ExternalCallStatus))}", name="ck_external_call_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(100))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(
        String(50)
    )  # inkloom_verify.schemas.ErrorCode value
    created_at: Mapped[datetime] = created_at_column()


class IdempotencyKey(Base):
    """Dedupes a client-retried write (e.g. `POST /api/reviews`) within one organisation."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "endpoint", "key", name="uq_idempotency_org_endpoint_key"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()


class ResultCache(Base):
    """Caches an engine report so identical content against identical source versions is not
    re-verified. `cache_key` is derived from content_version.text_sha256, the sorted source
    version ids/hashes used, and engine_contract_version/model_id (Phase 5 decides the exact
    derivation; the column just needs to be a stable, unique lookup key)."""

    __tablename__ = "result_cache"

    id: Mapped[uuid.UUID] = uuid_pk()
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="SET NULL")
    )
    report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
