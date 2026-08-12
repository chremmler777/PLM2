"""058: a lead time needs a unit.

"30 days" from a tool shop and "30 days" from a department planning board are
not the same promise: one is working days, the other is the calendar. Rolling
them up together silently understated the timeline by up to 40%.

Both costing_positions and costing_offers gain lead_time_unit, defaulting to
'calendar_days' — the reading every existing row was implicitly given, so the
backfill is the default and nothing changes meaning. Roll-ups convert business
days to calendar days before comparing (see CostingPosition.CALENDAR_PER_WEEK).

Written as its own revision rather than folded into 057, which may already have
run against the live database.

Revision ID: 058
Revises: 057
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    for table in ("costing_positions", "costing_offers"):
        if table not in tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "lead_time_unit" not in cols:
            op.add_column(table, sa.Column(
                "lead_time_unit", sa.String(length=20), nullable=False,
                server_default="calendar_days"))


def downgrade() -> None:
    pass  # forward-only
