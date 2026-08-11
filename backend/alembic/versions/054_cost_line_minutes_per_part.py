"""054: cost lines carry minutes per part.

The workbook's lifecycle section prices a change in machine minutes per part,
not only in one-off hours: a change that adds seconds to every shot costs
money forever. Negatives are meaningful and allowed — a change that SAVES
cycle time is exactly the case worth recording.

Nullable: one-time lines leave it empty, and every existing row predates it.

Revision ID: 054
Revises: 053
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "assessment_cost_line" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("assessment_cost_line")}
    if "minutes_per_part" not in cols:
        op.add_column("assessment_cost_line",
                      sa.Column("minutes_per_part", sa.Float(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
