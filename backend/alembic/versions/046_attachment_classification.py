"""046: attachments say what they are and what they answer.

A needs_info decision produces a question and, later, an answer — but both
landed as undifferentiated files, so nothing tied the answer to the ask. Two
columns close that loop:

  kind             general | info_request | info_response
  responds_to_id   the info_request this answers (info_response only)

Both are additive: every existing row is "general" with nothing to respond to.
The self-FK lives in the ORM only (SQLite cannot ADD COLUMN with an FK).

Revision ID: 046
Revises: 045
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_attachments" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_attachments")}
    if "kind" not in cols:
        op.add_column("change_attachments", sa.Column(
            "kind", sa.String(20), nullable=False, server_default="general"))
    if "responds_to_id" not in cols:
        op.add_column("change_attachments",
                      sa.Column("responds_to_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
