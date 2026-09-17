"""070: an estimated external line names its vendor.

Revision ID: 070
Revises: 069
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "costing_positions" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("costing_positions")}
    if "vendor_name" not in cols:
        op.add_column("costing_positions",
                      sa.Column("vendor_name", sa.String(120), nullable=True))


def downgrade() -> None:
    pass  # forward-only
