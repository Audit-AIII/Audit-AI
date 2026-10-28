"""Round 3 Phase 1: workspaces, team roles and invitations (docs/governance.md, section 4).

An organisation already is a workspace: every tenant-owned row resolves to one, and registration
has always created one per user. So no data moves. This migration only:

- marks each organisation personal or not, and records who created it;
- adds the `owner` and `writer` roles, and turns every existing `admin` (account owner) into
  `owner`. The legacy role names stay valid;
- adds `invitations`. A token is stored only as its sha256, and at most one invitation per email
  is open (neither accepted nor revoked) in a workspace at a time.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-28

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_MEMBERSHIP_ROLES = (
    "submitter",
    "source_manager",
    "reviewer",
    "approver",
    "admin",
    "legal_reviewer",
    "brand_manager",
)
_NEW_MEMBERSHIP_ROLES = ("owner", "writer") + _OLD_MEMBERSHIP_ROLES
_TEAM_ROLES = ("owner", "approver", "reviewer", "writer")


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "organisations",
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Every account so far came from registration (one organisation per person). The seed
    # script's demo organisation is the only one that may have several members; it is a team.
    op.execute(
        """
        UPDATE organisations o SET is_personal = (
            SELECT count(*) FROM memberships m WHERE m.organisation_id = o.id
        ) <= 1
        """
    )
    op.execute(
        """
        UPDATE organisations o SET created_by_user_id = (
            SELECT m.user_id FROM memberships m
            WHERE m.organisation_id = o.id AND m.role = 'admin'
            ORDER BY m.created_at ASC LIMIT 1
        )
        """
    )

    op.drop_constraint("ck_membership_role", "memberships", type_="check")
    op.create_check_constraint(
        "ck_membership_role", "memberships", f"role IN {_NEW_MEMBERSHIP_ROLES}"
    )
    op.execute("UPDATE memberships SET role = 'owner' WHERE role = 'admin'")

    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(f"role IN {_TEAM_ROLES}", name="ck_invitation_role"),
    )
    op.create_index(
        "uq_invitations_one_open_per_email",
        "invitations",
        ["organisation_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_invitations_one_open_per_email", table_name="invitations")
    op.drop_table("invitations")

    # Same reconciliation rule as 0008's downgrade: data must fit the narrower schema again.
    # Every new role has an older equivalent, so nothing has to be deleted.
    op.execute("UPDATE memberships SET role = 'admin' WHERE role = 'owner'")
    op.execute("UPDATE memberships SET role = 'submitter' WHERE role = 'writer'")
    op.drop_constraint("ck_membership_role", "memberships", type_="check")
    op.create_check_constraint(
        "ck_membership_role", "memberships", f"role IN {_OLD_MEMBERSHIP_ROLES}"
    )

    op.drop_column("organisations", "created_by_user_id")
    op.drop_column("organisations", "is_personal")
