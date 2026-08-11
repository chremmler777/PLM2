"""049: attachments can belong to one concern; concerns name their meeting.

A needs-info request is a self-contained exchange: the person asking may
attach a drawing that explains the question, Sales attaches the answer.
Hanging both off the change and hoping the filenames explain themselves loses
which document belongs to which question.

change_concerns also gains raised_by_meeting_id: a flag raised by a decision
should say which meeting (or email record) raised it, so the exchange traces
back to where it was decided. Manually raised concerns leave it null.

Both nullable, so existing rows are unaffected. The FKs live in the ORM only
(SQLite cannot ADD COLUMN with an FK).

Revision ID: 049
Revises: 048
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_attachments" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_attachments")}
    if "concern_id" not in cols:
        op.add_column("change_attachments",
                      sa.Column("concern_id", sa.Integer(), nullable=True))
        op.create_index("ix_change_attachments_concern_id",
                        "change_attachments", ["concern_id"])
    if "change_concerns" in insp.get_table_names():
        ccols = {c["name"] for c in insp.get_columns("change_concerns")}
        if "raised_by_meeting_id" not in ccols:
            op.add_column("change_concerns", sa.Column(
                "raised_by_meeting_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
