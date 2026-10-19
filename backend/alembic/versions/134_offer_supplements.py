"""134: supplements (ECR-solid §6 "After approval", §7).

Schema
  change_offers.kind   'offer' (the quote) | 'supplement' (sent after
                       approval: the changed positions only; the change
                       keeps its status)

Data: every existing row is an offer (server default).

Repeatable: the column is added once.

Revision ID: 134
Revises: 133
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "134"
down_revision = "133"
branch_labels = None
depends_on = None


def _have() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns("change_offers")}


def upgrade() -> None:
    if "kind" not in _have():
        op.add_column("change_offers", sa.Column(
            "kind", sa.String(12), nullable=False, server_default="offer"))


def downgrade() -> None:
    if "kind" in _have():
        op.drop_column("change_offers", "kind")
