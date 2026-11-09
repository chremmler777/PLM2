"""156: a document can belong to one case of a checklist row (Christoph 2026-11-08).

Schema
  change_attachments.case_ref   the id of the Internal / External
                                modification case it documents (the case ids
                                live in the assessment's details.impacts[].cases);
                                NULL = a document of the whole assessment

Repeatable: the column is added once. Downgrade drops it (the documents stay,
filed against the assessment).

Revision ID: 156
Revises: 155
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "156"
down_revision = "155"
branch_labels = None
depends_on = None


def upgrade():
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("change_attachments")}
    if "case_ref" not in cols:
        op.add_column("change_attachments", sa.Column("case_ref", sa.String(40), nullable=True))


def downgrade():
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("change_attachments")}
    if "case_ref" in cols:
        op.drop_column("change_attachments", "case_ref")
