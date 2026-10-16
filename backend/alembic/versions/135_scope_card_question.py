"""135: a question on a scope change card (ECR-solid §6 step 1, "Missing
info is a question").

Schema (change_scope_changes)
  question   JSON, nullable: the customer question that holds the lead's
             accept of a requested card: {text, by, at} while open, plus
             {answer, ref, attachment_id, answered_by, answered_at} once
             Sales filed the customer's answer

Data: none (an existing card has no question; it is decided as before).

Repeatable: the column is added once.

Revision ID: 135
Revises: 134
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "135"
down_revision = "134"
branch_labels = None
depends_on = None


def _have() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns("change_scope_changes")}


def upgrade() -> None:
    if "question" not in _have():
        op.add_column("change_scope_changes", sa.Column("question", sa.JSON(), nullable=True))


def downgrade() -> None:
    if "question" in _have():
        op.drop_column("change_scope_changes", "question")
