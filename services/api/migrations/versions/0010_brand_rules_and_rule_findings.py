"""Brand rules (terminology, compliance, accessibility) and rule findings.

Wires Member 2's rules module (inkloom_verify.rules, services/verification/RULES_HANDOFF.md) into
reviews. All additive and nullable, so existing rows and responses are unchanged:

* brand_profiles.rules: the brand's validated `BrandRules` JSON (null = accessibility defaults only);
* findings.rule_id / rule_type / scope / suggestion_basis: which rule a `check_type = 'rule'`
  finding comes from (null on claim findings);
* reviews.rules_status / rule_checks: whether the rules ran (complete, incomplete, not_applied;
  null on reviews from before this migration) and one check record per rule, so "not checked"
  is never shown as "passed".

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-24

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RULES_STATUSES = ("complete", "incomplete", "not_applied")
_SCOPES = ("text", "document")


def upgrade() -> None:
    op.add_column("brand_profiles", sa.Column("rules", postgresql.JSONB(), nullable=True))

    op.add_column("findings", sa.Column("rule_id", sa.String(128), nullable=True))
    op.add_column("findings", sa.Column("rule_type", sa.String(40), nullable=True))
    op.add_column("findings", sa.Column("scope", sa.String(10), nullable=True))
    op.add_column("findings", sa.Column("suggestion_basis", sa.String(30), nullable=True))
    op.create_check_constraint("ck_finding_scope", "findings", f"scope IS NULL OR scope IN {_SCOPES}")

    op.add_column("reviews", sa.Column("rules_status", sa.String(20), nullable=True))
    op.add_column("reviews", sa.Column("rule_checks", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_review_rules_status", "reviews", f"rules_status IS NULL OR rules_status IN {_RULES_STATUSES}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_rules_status", "reviews", type_="check")
    op.drop_column("reviews", "rule_checks")
    op.drop_column("reviews", "rules_status")

    op.drop_constraint("ck_finding_scope", "findings", type_="check")
    op.drop_column("findings", "suggestion_basis")
    op.drop_column("findings", "scope")
    op.drop_column("findings", "rule_type")
    op.drop_column("findings", "rule_id")

    op.drop_column("brand_profiles", "rules")
