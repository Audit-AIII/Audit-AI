"""Phase 7 task 4: source_versions.section_hashes, evidence_links.cited_section_hash.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_versions",
        sa.Column("section_hashes", postgresql.JSONB, nullable=False, server_default="[]"),
    )
    op.add_column("evidence_links", sa.Column("cited_section_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence_links", "cited_section_hash")
    op.drop_column("source_versions", "section_hashes")
