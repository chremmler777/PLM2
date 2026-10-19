"""120: an override is bound to its rule (ECR-solid C6, lane L2).

Schema
  change_transition_deviations.guard_key     the soft rule the override waives
                                             ('costing_not_finalized', 'gate:budget',
                                             'price_open' for an Absorb, ...)
  change_transition_deviations.guard_reason  the rule's words when it was asked
  change_transition_deviations.reason_code   the reason pick (customer_date,
                                             in_parallel, not_applicable, other;
                                             Absorb: goodwill, small_amount,
                                             our_error, other)

Data
  none: rows written before the binding keep guard_key NULL. Such a row is
  read as before (it waives whatever holds its target status), so an
  in-flight change with an approved deviation still moves; a pending one is
  bound to the rule that holds the hop when it is decided.

Repeatable: every column is added once.

Revision ID: 120
Revises: 119
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "120"
down_revision = "119"
branch_labels = None
depends_on = None

TABLE = "change_transition_deviations"
COLUMNS = (
    sa.Column("guard_key", sa.String(64), nullable=True),
    sa.Column("guard_reason", sa.Text(), nullable=True),
    sa.Column("reason_code", sa.String(30), nullable=True),
)


def _has_table(table: str) -> bool:
    return table in inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_table(TABLE):
        return
    have = _columns(TABLE)
    missing = [c for c in COLUMNS if c.name not in have]
    if not missing:
        return
    with op.batch_alter_table(TABLE) as batch:
        for col in missing:
            batch.add_column(col.copy())


def downgrade() -> None:
    if not _has_table(TABLE):
        return
    have = _columns(TABLE)
    present = [c.name for c in COLUMNS if c.name in have]
    if not present:
        return
    with op.batch_alter_table(TABLE) as batch:
        for name in present:
            batch.drop_column(name)
