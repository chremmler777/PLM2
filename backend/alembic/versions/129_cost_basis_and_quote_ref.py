"""129: the basis of every costing position and the supplier's quote
reference (ECR-solid spec §4 costing positions, C25).

Schema
  costing_positions.basis          rate | quote | same_as | estimate (NULL
                                   legacy: read from kind and pricing)
  costing_positions.basis_ref      estimate: its reference (earlier tool,
                                   supplier figure + date)
  costing_positions.basis_part_id  same_as: the part it is the same as
  costing_positions.basis_differs  same_as: what differs (size, cavities,
                                   material, slides)
  costing_positions.estimate_check quote vs the estimate an offer or the
                                   internal approval was given on: within |
                                   above
  costing_positions.estimate_over  above: by how much (money)
  costing_offers.quote_ref         the supplier's quote number
  costing_offers.quoted_on         its date
  costing_offers.valid_until       how long it holds

Data: none. Positions of in-flight changes keep basis NULL (read from their
kind and pricing); a department that has not finalized names its basis at
its finalize.

Repeatable: every column is added once.

Revision ID: 129
Revises: 128
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "129"
down_revision = "128"
branch_labels = None
depends_on = None

COLUMNS = {
    "costing_positions": (
        ("basis", lambda: sa.String(20), None),
        ("basis_ref", lambda: sa.String(255), None),
        ("basis_part_id", lambda: sa.Integer(), "parts"),
        ("basis_differs", lambda: sa.Text(), None),
        ("estimate_check", lambda: sa.String(10), None),
        ("estimate_over", lambda: sa.Numeric(14, 2), None),
    ),
    "costing_offers": (
        ("quote_ref", lambda: sa.String(120), None),
        ("quoted_on", lambda: sa.Date(), None),
        ("valid_until", lambda: sa.Date(), None),
    ),
}


def _have(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table, cols in COLUMNS.items():
        have = _have(table)
        for name, typ, fk in cols:
            if name in have:
                continue
            args = [sa.ForeignKey(f"{fk}.id")] if fk else []
            op.add_column(table, sa.Column(name, typ(), *args, nullable=True))


def downgrade() -> None:
    for table, cols in COLUMNS.items():
        have = _have(table)
        for name, _, _ in reversed(cols):
            if name in have:
                op.drop_column(table, name)
