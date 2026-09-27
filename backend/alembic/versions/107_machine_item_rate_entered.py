"""107: a per-machine rate typed in the plant's local currency.

cost_sheet_machine_item_rates (105) gets entered_rate + entered_currency,
like cost_sheet_rates and cost_sheet_machine_rates got them in 106: a
MachineDB press at a two-currency plant (Silao: USD quote, MXN local) can
have its own rate typed in either currency. The typed number is kept;
hourly_rate stays the rate in the row's currency, computed from the typed
number at the version's exchange rate.

Guarded (a column that exists already is left alone), dialect-neutral.
Downgrade drops the two columns.

Revision ID: 107
Revises: 106
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "107"
down_revision = "106"
branch_labels = None
depends_on = None

TABLE = "cost_sheet_machine_item_rates"


def _cols(bind):
    return {c["name"] for c in inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE not in set(inspect(bind).get_table_names()):
        return
    have = _cols(bind)
    if "entered_rate" not in have:
        op.add_column(TABLE, sa.Column("entered_rate", sa.Numeric(12, 2), nullable=True))
    if "entered_currency" not in have:
        op.add_column(TABLE, sa.Column("entered_currency", sa.String(3), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE not in set(inspect(bind).get_table_names()):
        return
    have = [c for c in ("entered_rate", "entered_currency") if c in _cols(bind)]
    if not have:
        return
    with op.batch_alter_table(TABLE) as batch:
        for c in have:
            batch.drop_column(c)
