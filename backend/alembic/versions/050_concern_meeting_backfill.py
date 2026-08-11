"""050: make sure change_concerns.raised_by_meeting_id exists.

049 adds this column, but a database that was stamped 049 while the column
was still missing (an upgrade that ran against an earlier copy of that file)
would never get it — and alembic will not revisit an applied revision. This
revision closes that gap and no-ops everywhere else, so both histories
converge on the same schema.

Revision ID: 050
Revises: 049
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_concerns" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_concerns")}
    if "raised_by_meeting_id" not in cols:
        # FK in the ORM only (SQLite cannot ADD COLUMN with an FK).
        op.add_column("change_concerns",
                      sa.Column("raised_by_meeting_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
