"""Phase 9 stretch item 1: risk-based approval routing.

Two new membership roles (legal_reviewer, brand_manager) and reviews.required_reviewer_role,
the deterministic routing target computed once a review has findings to look at.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_MEMBERSHIP_ROLES = ("submitter", "source_manager", "reviewer", "approver", "admin")
_NEW_MEMBERSHIP_ROLES = _OLD_MEMBERSHIP_ROLES + ("legal_reviewer", "brand_manager")
_ROUTABLE_REVIEWER_ROLES = ("legal_reviewer", "brand_manager")


def upgrade() -> None:
    op.drop_constraint("ck_membership_role", "memberships", type_="check")
    op.create_check_constraint("ck_membership_role", "memberships", f"role IN {_NEW_MEMBERSHIP_ROLES}")

    op.add_column("reviews", sa.Column("required_reviewer_role", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_review_required_reviewer_role",
        "reviews",
        f"required_reviewer_role IN {_ROUTABLE_REVIEWER_ROLES} OR required_reviewer_role IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_required_reviewer_role", "reviews", type_="check")
    op.drop_column("reviews", "required_reviewer_role")

    # A real downgrade must reconcile data that no longer fits the old, narrower schema, not
    # just blindly re-add the stricter constraint and let it fail - caught by this repo's own
    # test_migrations.py once a membership actually used one of these roles (e.g. the seed
    # script's legal_reviewer/brand_manager demo users). Deleting rather than remapping to some
    # other role: there is no equivalent role under the old schema, and a downgrade already
    # means "this feature no longer exists here."
    op.execute("DELETE FROM memberships WHERE role IN ('legal_reviewer', 'brand_manager')")
    op.drop_constraint("ck_membership_role", "memberships", type_="check")
    op.create_check_constraint("ck_membership_role", "memberships", f"role IN {_OLD_MEMBERSHIP_ROLES}")
