"""Phase 6: content_items.brand_profile_id, content_versions.is_current.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("brand_profile_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_content_items_brand_profile_id", "content_items", "brand_profiles", ["brand_profile_id"], ["id"]
    )
    op.create_index("ix_content_items_brand_profile_id", "content_items", ["brand_profile_id"])

    op.add_column(
        "content_versions", sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true())
    )
    # Exactly one current version per content item, enforced by the database itself - not just
    # application code ("the old approval becomes historical only").
    op.create_index(
        "uq_content_versions_one_current_per_item",
        "content_versions",
        ["content_item_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index("uq_content_versions_one_current_per_item", table_name="content_versions")
    op.drop_column("content_versions", "is_current")
    op.drop_index("ix_content_items_brand_profile_id", table_name="content_items")
    op.drop_constraint("fk_content_items_brand_profile_id", "content_items", type_="foreignkey")
    op.drop_column("content_items", "brand_profile_id")
