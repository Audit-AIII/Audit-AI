"""Add brand_sources.source_type and storage_path (Phase 4: file uploads).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCE_FILE_TYPES = ("txt", "pdf", "docx")


def upgrade() -> None:
    op.add_column("brand_sources", sa.Column("source_type", sa.String(10), nullable=True))
    op.add_column("brand_sources", sa.Column("storage_path", sa.Text, nullable=True))
    op.create_check_constraint("ck_brand_source_file_type", "brand_sources", f"source_type IN {SOURCE_FILE_TYPES}")


def downgrade() -> None:
    op.drop_constraint("ck_brand_source_file_type", "brand_sources", type_="check")
    op.drop_column("brand_sources", "storage_path")
    op.drop_column("brand_sources", "source_type")
