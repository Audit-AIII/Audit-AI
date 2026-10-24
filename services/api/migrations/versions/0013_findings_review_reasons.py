"""findings.review_reasons: why a finding needs a person (the engine's ClaimReviewReason values).

The engine's decision policy can send a SUPPORTED claim to review (weak evidence, below the
policy's strength, a compound claim on one quote); without the reason the UI can only say "you need
to decide on this one". Nullable and additive: null on rule findings, stub findings and rows
written before this migration.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-24

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("review_reasons", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("findings", "review_reasons")
