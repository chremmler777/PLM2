"""042: concerns gain a department and a resolution note.

A concern used to be a scoping-phase, change-level flag. It now also works
during assessment, where it belongs to ONE department and acts as that
department's soft hold: the department cannot finalize its own assessment
while it has an open concern. Clearing it demands `resolution_note` — the
"how was it addressed" evidence — so the hold is lifted on the record.

Both columns are nullable: scoping concerns keep department_id NULL and are
withdrawn without a note, exactly as before.

Revision ID: 042
Revises: 041
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_concerns" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_concerns")}
    if "department_id" not in cols:
        # FK lives in the ORM only (SQLite cannot ADD COLUMN with an FK)
        op.add_column("change_concerns",
                      sa.Column("department_id", sa.Integer(), nullable=True))
    if "resolution_note" not in cols:
        op.add_column("change_concerns",
                      sa.Column("resolution_note", sa.Text(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
