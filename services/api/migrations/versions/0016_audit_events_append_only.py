"""Round 3 Phase 5: audit_events is append-only at the database level (docs/governance.md).

The application only ever inserts audit events. This trigger makes that a guarantee: any UPDATE
of an audit row is refused by Postgres itself, whoever sends it. DELETE stays possible, because
deleting a whole workspace (organisation) removes its audit rows by ON DELETE CASCADE.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-28

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION audit_events_refuse_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: rows cannot be updated';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only BEFORE UPDATE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_refuse_update()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_refuse_update()")
