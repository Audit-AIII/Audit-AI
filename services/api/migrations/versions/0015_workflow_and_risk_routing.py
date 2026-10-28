"""Round 3 Phase 4: workflow status and risk routing on drafts (docs/governance.md sections 4, 6, 7).

Additive only; nothing is renamed or removed except one CHECK constraint (decision D3):

- content_items: workflow_status (backfilled from each draft's latest review of its current
  version), owner, assigned reviewer, the stored routing decision, and who submitted / reviewed;
- audit_events: content_item_id, version_number and note, so a draft's audit history is one
  indexed query (Phase 5);
- findings: the strict CHECK on verification_status is dropped, so a verification status the
  engine adds later is stored as-is instead of being refused (it is routed as medium risk).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-28

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WORKFLOW = (
    "draft",
    "submitted",
    "in_review",
    "needs_changes",
    "reviewed",
    "approved",
    "rejected",
    "published",
    "blocked",
)
_VERIFICATION_STATUSES = (
    "supported",
    "contradicted",
    "unverified",
    "conflicting_sources",
    "not_applicable",
)


def _user_fk(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("workflow_status", sa.String(30), nullable=False, server_default="draft"),
    )
    op.create_check_constraint(
        "ck_content_item_workflow_status", "content_items", f"workflow_status IN {_WORKFLOW}"
    )
    op.add_column("content_items", _user_fk("owner_user_id"))
    op.add_column("content_items", _user_fk("assigned_reviewer_id"))
    op.add_column("content_items", sa.Column("risk_level", sa.String(20), nullable=True))
    op.add_column(
        "content_items", sa.Column("required_reviewer_role", sa.String(20), nullable=True)
    )
    op.add_column("content_items", sa.Column("routing_reason_code", sa.String(60), nullable=True))
    op.add_column("content_items", sa.Column("routing_reason_text", sa.Text(), nullable=True))
    op.add_column("content_items", sa.Column("routing_details", postgresql.JSONB(), nullable=True))
    op.add_column(
        "content_items",
        sa.Column("routed_review_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("content_items", _user_fk("submitted_by"))
    op.add_column(
        "content_items", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("content_items", _user_fk("reviewed_by"))
    op.add_column(
        "content_items", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "content_items",
        sa.Column("workflow_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute("UPDATE content_items SET owner_user_id = created_by")
    # Every draft starts from what its latest review of the current version says. Past
    # decisions (including old self-approvals) stay as history and are never re-checked.
    op.execute(
        """
        UPDATE content_items ci SET workflow_status = CASE r.status
            WHEN 'approved' THEN 'approved'
            WHEN 'rejected' THEN 'rejected'
            WHEN 'changes_requested' THEN 'needs_changes'
            WHEN 'failed' THEN 'blocked'
            WHEN 'source_changed' THEN 'blocked'
            ELSE 'draft' END
        FROM (
            SELECT DISTINCT ON (cv.content_item_id) cv.content_item_id, rv.status
            FROM content_versions cv JOIN reviews rv ON rv.content_version_id = cv.id
            WHERE cv.is_current
            ORDER BY cv.content_item_id, rv.created_at DESC, rv.id DESC
        ) r
        WHERE r.content_item_id = ci.id
        """
    )

    op.add_column(
        "audit_events",
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_audit_events_content_item_id", "audit_events", ["content_item_id"])
    op.add_column("audit_events", sa.Column("version_number", sa.Integer(), nullable=True))
    op.add_column("audit_events", sa.Column("note", sa.Text(), nullable=True))

    op.drop_constraint("ck_finding_verification_status", "findings", type_="check")


def downgrade() -> None:
    # Unknown statuses must fit the restored constraint: they were always treated as unverified.
    op.execute(
        f"UPDATE findings SET verification_status = 'unverified' "
        f"WHERE verification_status NOT IN {_VERIFICATION_STATUSES}"
    )
    op.create_check_constraint(
        "ck_finding_verification_status",
        "findings",
        f"verification_status IN {_VERIFICATION_STATUSES}",
    )
    op.drop_column("audit_events", "note")
    op.drop_column("audit_events", "version_number")
    op.drop_index("ix_audit_events_content_item_id", table_name="audit_events")
    op.drop_column("audit_events", "content_item_id")

    op.drop_constraint("ck_content_item_workflow_status", "content_items", type_="check")
    for column in (
        "workflow_updated_at",
        "reviewed_at",
        "reviewed_by",
        "submitted_at",
        "submitted_by",
        "routed_review_id",
        "routing_details",
        "routing_reason_text",
        "routing_reason_code",
        "required_reviewer_role",
        "risk_level",
        "assigned_reviewer_id",
        "owner_user_id",
        "workflow_status",
    ):
        op.drop_column("content_items", column)
