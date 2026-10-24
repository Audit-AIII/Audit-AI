"""Intent-lock, per-finding Dismiss and comments on findings (Phase 7).

* content_versions.locked_phrases: the writer's must-keep phrases (Intent-lock; engine semantics in
  inkloom_verify.intent_lock). Suggestions that would remove one are never offered.
* finding_decisions: per-finding Dismiss / restore as separate rows - the finding itself (verdict,
  evidence, explanation) is never changed by a decision.
* finding_comments: a comment thread per finding.

Additive: existing rows get an empty lock list and no decisions or comments.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTIONS = ("dismissed", "restored")


def upgrade() -> None:
    op.add_column(
        "content_versions",
        sa.Column("locked_phrases", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    op.create_table(
        "finding_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("findings.finding_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"action IN {_ACTIONS}", name="ck_finding_decision_action"),
    )
    op.create_index("ix_finding_decisions_finding_id", "finding_decisions", ["finding_id"])

    op.create_table(
        "finding_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("findings.finding_id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_finding_comments_finding_id", "finding_comments", ["finding_id"])


def downgrade() -> None:
    op.drop_index("ix_finding_comments_finding_id", table_name="finding_comments")
    op.drop_table("finding_comments")
    op.drop_index("ix_finding_decisions_finding_id", table_name="finding_decisions")
    op.drop_table("finding_decisions")
    op.drop_column("content_versions", "locked_phrases")
