"""external_call_log.review_id / result_cache.review_id: ON DELETE SET NULL, not RESTRICT.

Same bug class as 0004 (evidence_links), found while testing Phase 5's cache wiring: deleting a
review (or an organisation, cascading to its reviews) that already has a logged external call or
a cache row pointing at it crashed with a foreign key violation instead of degrading gracefully -
both rows are durable operational/audit records that should outlive the review they reference,
not be blocked or silently cascaded away.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("external_call_log_review_id_fkey", "external_call_log", type_="foreignkey")
    op.create_foreign_key(
        "external_call_log_review_id_fkey", "external_call_log", "reviews", ["review_id"], ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("result_cache_review_id_fkey", "result_cache", type_="foreignkey")
    op.create_foreign_key(
        "result_cache_review_id_fkey", "result_cache", "reviews", ["review_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("result_cache_review_id_fkey", "result_cache", type_="foreignkey")
    op.create_foreign_key(
        "result_cache_review_id_fkey", "result_cache", "reviews", ["review_id"], ["id"],
    )
    op.drop_constraint("external_call_log_review_id_fkey", "external_call_log", type_="foreignkey")
    op.create_foreign_key(
        "external_call_log_review_id_fkey", "external_call_log", "reviews", ["review_id"], ["id"],
    )
