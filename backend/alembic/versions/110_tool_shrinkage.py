"""110: the shrinkage a tool is cut with.

parts.tool_shrink_parallel_pct / tool_shrink_normal_pct: mould shrinkage in %
the tool steel is dimensioned with, parallel (flow direction) and normal
(across flow). Glass-filled resins shrink differently in the two directions.
Tools only; set and confirmed by engineering, not copied from the datasheet.

Guarded (a column that exists already is left alone), dialect-neutral.

Revision ID: 110
Revises: 109
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "110"
down_revision = "109"
branch_labels = None
depends_on = None

TABLE = "parts"
COLUMNS = ("tool_shrink_parallel_pct", "tool_shrink_normal_pct")


def _cols(bind):
    return {c["name"] for c in inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE not in set(inspect(bind).get_table_names()):
        return
    have = _cols(bind)
    for name in COLUMNS:
        if name not in have:
            op.add_column(TABLE, sa.Column(name, sa.Numeric(5, 3), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE not in set(inspect(bind).get_table_names()):
        return
    have = _cols(bind)
    with op.batch_alter_table(TABLE) as batch:
        for name in COLUMNS:
            if name in have:
                batch.drop_column(name)
