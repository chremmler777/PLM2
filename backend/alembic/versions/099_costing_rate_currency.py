"""099: the rate's currency apart from the money's, and "no rate" on grid lines.

- costing_positions.rate_currency: the currency of the rate snapshot (the
  cost sheet row's). costing_positions.currency stays the money currency of
  the line (est_cost and offers: the costing plant's). Backfilled from
  currency for lines that carry a snapshot.
- costing_positions: a snapshot that found no rate is not a snapshot:
  rate_on is cleared where rate is NULL, so the line is priced live until a
  rate exists (costing_rates.snapshot_position).
- assessment_cost_line.rate_snapshot becomes nullable: a grid line seeded
  where the cost sheet has no rate stores NULL (and no rate_source), never 0.

Dialect-neutral (batch mode for the nullability change on SQLite).

Revision ID: 099
Revises: 098
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "099"
down_revision = "098"
branch_labels = None
depends_on = None


def _cols(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "costing_positions" in tables:
        if "rate_currency" not in _cols(bind, "costing_positions"):
            op.add_column("costing_positions",
                          sa.Column("rate_currency", sa.String(3), nullable=True))
        op.execute("UPDATE costing_positions SET rate_currency = currency "
                   "WHERE rate_on IS NOT NULL AND rate_currency IS NULL")
        op.execute("UPDATE costing_positions SET rate_on = NULL "
                   "WHERE rate IS NULL AND rate_on IS NOT NULL")
    if "assessment_cost_line" in tables:
        with op.batch_alter_table("assessment_cost_line") as batch:
            batch.alter_column("rate_snapshot", existing_type=sa.Float(),
                               nullable=True, existing_server_default="0")


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "assessment_cost_line" in tables:
        op.execute("UPDATE assessment_cost_line SET rate_snapshot = 0 "
                   "WHERE rate_snapshot IS NULL")
        with op.batch_alter_table("assessment_cost_line") as batch:
            batch.alter_column("rate_snapshot", existing_type=sa.Float(),
                               nullable=False, existing_server_default="0")
    if "costing_positions" in tables and "rate_currency" in _cols(bind, "costing_positions"):
        op.drop_column("costing_positions", "rate_currency")
