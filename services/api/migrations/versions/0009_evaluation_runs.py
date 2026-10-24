"""Trust Scorecard: evaluation_runs.

One row per run of the engine's labelled evaluation (POST /api/evaluations), scoped to the
account (organisation) that ran it. Only measured numbers are stored (`metrics`), with the
dataset and prompt versions they were measured with and a plain-language note on their limits.
A run that could not start (no provider configured) stores nothing.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES = ("completed", "partial")


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engine_prompt_version", sa.String(50), nullable=True),
        sa.Column("dataset_version", sa.String(100), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("limits_note", sa.Text(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN {_STATUSES}", name="ck_evaluation_run_status"),
        sa.CheckConstraint("sample_size >= 0", name="ck_evaluation_run_sample_size"),
    )
    op.create_index("ix_evaluation_runs_organisation_ran_at", "evaluation_runs", ["organisation_id", "ran_at"])
    op.create_index("ix_evaluation_runs_created_by", "evaluation_runs", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_created_by", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_organisation_ran_at", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
