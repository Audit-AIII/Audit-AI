"""evidence_links.source_id / source_version_id: ON DELETE SET NULL, not RESTRICT.

Found while testing Phase 7: a brand_source is never hard-deleted by the app (withdraw only
changes status), but without this, any future hard-delete path would crash with a foreign key
violation instead of degrading gracefully - the evidence record should survive for audit
purposes with the dangling reference cleared, not be blocked or silently cascaded away.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("evidence_links_source_id_fkey", "evidence_links", type_="foreignkey")
    op.create_foreign_key(
        "evidence_links_source_id_fkey", "evidence_links", "brand_sources", ["source_id"], ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("evidence_links_source_version_id_fkey", "evidence_links", type_="foreignkey")
    op.create_foreign_key(
        "evidence_links_source_version_id_fkey", "evidence_links", "source_versions", ["source_version_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("evidence_links_source_version_id_fkey", "evidence_links", type_="foreignkey")
    op.create_foreign_key(
        "evidence_links_source_version_id_fkey", "evidence_links", "source_versions", ["source_version_id"], ["id"],
    )
    op.drop_constraint("evidence_links_source_id_fkey", "evidence_links", type_="foreignkey")
    op.create_foreign_key(
        "evidence_links_source_id_fkey", "evidence_links", "brand_sources", ["source_id"], ["id"],
    )
