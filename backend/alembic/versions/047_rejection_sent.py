"""047: a rejected customer change is only done once the customer was told.

Closing a rejected customer-relevant change now requires a rejection letter on
file AND a confirmed send; these two columns are that confirmation. Both
nullable — internal rejections close without either, and every historical row
predates the rule.

The FK lives in the ORM only (SQLite cannot ADD COLUMN with an FK).

Revision ID: 047
Revises: 046
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_requests" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_requests")}
    if "rejection_sent_at" not in cols:
        op.add_column("change_requests",
                      sa.Column("rejection_sent_at", sa.DateTime(), nullable=True))
    if "rejection_sent_by" not in cols:
        op.add_column("change_requests",
                      sa.Column("rejection_sent_by", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
