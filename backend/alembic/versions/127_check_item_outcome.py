"""127: how a department closed a check item in its assessment (ECR-solid
spec §4 "Check items first").

Schema (change_concerns)
  check_outcome   answered | not_relevant | assumed: the inline close of a
                  C33 check item by its owning department; NULL on every
                  other row (questions, risks, check items closed before
                  this or by their author / Project Management)

Data: none. Open check items of in-flight changes stay open; closed ones
keep their resolution note.

Repeatable: the column is added once.

Revision ID: 127
Revises: 126
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "127"
down_revision = "126"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns("change_concerns")}


def upgrade() -> None:
    if "check_outcome" not in _columns():
        op.add_column("change_concerns",
                      sa.Column("check_outcome", sa.String(20), nullable=True))


def downgrade() -> None:
    if "check_outcome" in _columns():
        op.drop_column("change_concerns", "check_outcome")
