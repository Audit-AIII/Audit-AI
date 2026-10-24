"""Trust Scorecard runs (migration 0009). One row per POST /api/evaluations that actually ran."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..statuses import EvaluationRunStatus, values
from .base import Base, created_at_column, uuid_pk


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN {tuple(values(EvaluationRunStatus))}", name="ck_evaluation_run_status"
        ),
        CheckConstraint("sample_size >= 0", name="ck_evaluation_run_sample_size"),
        Index("ix_evaluation_runs_organisation_ran_at", "organisation_id", "ran_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    engine_prompt_version: Mapped[str | None] = mapped_column(String(50))
    dataset_version: Mapped[str] = mapped_column(String(100), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # Measured numbers only (catch/false-positive rates with their numerators and denominators,
    # per-check breakdown, latency, provider failure rate) - never model-reported confidence.
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    limits_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = created_at_column()
