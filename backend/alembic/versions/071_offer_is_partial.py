"""071: a vendor offer is a full quote (alternative) or a partial quote (part).

Parts are always counted and summed; alternatives compete and the starred
one counts. Additive, dialect-neutral.

Revision ID: 071
Revises: 070
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "costing_offers" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("costing_offers")}
    if "is_partial" not in cols:
        op.add_column("costing_offers",
                      sa.Column("is_partial", sa.Boolean(), nullable=False,
                                server_default=sa.false()))


def downgrade() -> None:
    pass  # forward-only
