"""076: parts.tier1_part_number.

When we are Tier 2, the Tier 1 (e.g. Brose) numbers the part in its own scheme
next to the OEM number in customer_part_number.

Revision ID: 076
Revises: 075
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "tier1_part_number" not in _cols(insp, "parts"):
        op.add_column("parts", sa.Column("tier1_part_number", sa.String(100), nullable=True))
        op.create_index("ix_parts_tier1_part_number", "parts", ["tier1_part_number"])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if "tier1_part_number" in _cols(insp, "parts"):
        op.drop_index("ix_parts_tier1_part_number", table_name="parts")
        op.drop_column("parts", "tier1_part_number")
