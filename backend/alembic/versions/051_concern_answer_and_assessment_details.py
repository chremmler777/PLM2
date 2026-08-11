"""051: concern answers as stored comments; per-department assessment details.

Two additive column groups.

change_concerns.answer_note/answered_at/answered_by — Sales answers a question
as a COMMENT on it. Answering is not settling: the concern stays open until
the side that raised it (or a PM) withdraws it, and the resolution note can
reference the answer. Re-answering overwrites the fields; the changelog keeps
every round.

change_assessments.details — JSON-serialized dict of a department's own
questionnaire answers (Packaging's "is packaging impacted?" and what kind).
Generic on purpose: a per-department table for each questionnaire would be a
schema migration every time a question changes.

Revision ID: 051
Revises: 050
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "change_concerns" in tables:
        cols = {c["name"] for c in insp.get_columns("change_concerns")}
        if "answer_note" not in cols:
            op.add_column("change_concerns",
                          sa.Column("answer_note", sa.Text(), nullable=True))
        if "answered_at" not in cols:
            op.add_column("change_concerns",
                          sa.Column("answered_at", sa.DateTime(), nullable=True))
        if "answered_by" not in cols:
            # FK in the ORM only (SQLite cannot ADD COLUMN with an FK).
            op.add_column("change_concerns",
                          sa.Column("answered_by", sa.Integer(), nullable=True))

    if "change_assessments" in tables:
        cols = {c["name"] for c in insp.get_columns("change_assessments")}
        if "details" not in cols:
            op.add_column("change_assessments",
                          sa.Column("details", sa.Text(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
