"""findings.safer_wording: the engine's softened wording for an unverified claim.

Engine contract (services/verification/CONTRACTS.md, "Mapping to Member 3's shared values"):
`suggested_correction` is evidence-backed only; a softened wording for a NOT_ENOUGH_EVIDENCE claim
is not evidence-backed, so it gets its own column. Nullable and additive.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-24

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("safer_wording", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("findings", "safer_wording")
