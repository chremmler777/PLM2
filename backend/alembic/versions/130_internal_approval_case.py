"""130: the internal approval's case (ECR-solid spec §5, P9).

Schema (change_requests)
  internal_rationale      why we spend it: saving | quality | capacity |
                          safety | maintenance | other
  internal_volume         the annual volume the saving runs on (pcs / year)
  internal_saving         the saving per year (money)
  internal_saving_basis   calculated | estimate
  The payback (months) is computed from the approved amount and the saving.

Data: none. Changes approved before keep their approval; an open internal
approval names its case when it is given.

Repeatable: every column is added once.

Revision ID: 130
Revises: 129
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "130"
down_revision = "129"
branch_labels = None
depends_on = None

COLUMNS = (
    ("internal_rationale", lambda: sa.String(20)),
    ("internal_volume", lambda: sa.Float()),
    ("internal_saving", lambda: sa.Float()),
    ("internal_saving_basis", lambda: sa.String(12)),
)


def _have() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns("change_requests")}


def upgrade() -> None:
    have = _have()
    for name, typ in COLUMNS:
        if name not in have:
            op.add_column("change_requests", sa.Column(name, typ(), nullable=True))


def downgrade() -> None:
    have = _have()
    for name, _ in reversed(COLUMNS):
        if name in have:
            op.drop_column("change_requests", name)
