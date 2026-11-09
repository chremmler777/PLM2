"""158: spare part lines say if they are time critical (Christoph 2026-11-09).

"It needs to be identified if spare parts are time critical or not, that
changes the sales timing." costing_positions.time_critical: True = the spare
part is needed for the change and counts for the lead time; False = left out
of the lead time; NULL = not answered (Finalize asks for it).

Revision ID: 158
Revises: 157
"""
import sqlalchemy as sa
from alembic import op

revision = "158"
down_revision = "157"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("costing_positions",
                  sa.Column("time_critical", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("costing_positions", "time_critical")
