"""077: tool fields on parts.

Cavities, toolmaker, machine tonnage class and target cycle time for
item_category = tool. Nullable, meaningless on articles (the API refuses them
there).

Revision ID: 077
Revises: 076
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None

COLUMNS = [
    sa.Column("tool_cavities", sa.Integer(), nullable=True),
    sa.Column("toolmaker_id", sa.Integer(),
              sa.ForeignKey("suppliers.id", name="fk_parts_toolmaker_id_suppliers"), nullable=True),
    sa.Column("tool_tonnage_class", sa.Integer(), nullable=True),
    sa.Column("tool_cycle_time_s", sa.Numeric(6, 1), nullable=True),
]


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = inspect(op.get_bind())
    existing = _cols(insp, "parts")
    # batch mode: adding toolmaker_id (an FK column) needs table rebuild on SQLite
    with op.batch_alter_table("parts") as batch:
        for col in COLUMNS:
            if col.name not in existing:
                batch.add_column(col.copy())
    if "toolmaker_id" not in existing:
        op.create_index("ix_parts_toolmaker_id", "parts", ["toolmaker_id"])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    existing = _cols(insp, "parts")
    if "toolmaker_id" in existing:
        op.drop_index("ix_parts_toolmaker_id", table_name="parts")
    # batch mode: dropping toolmaker_id (an FK column) needs table rebuild on SQLite
    with op.batch_alter_table("parts") as batch:
        for col in reversed(COLUMNS):
            if col.name in existing:
                batch.drop_column(col.name)
