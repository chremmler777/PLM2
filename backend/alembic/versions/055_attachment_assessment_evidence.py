"""055: attachments can belong to one assessment.

A department's assessment is a claim — feasible, three days, this much cost —
and a claim is worth more with the moldflow report or test result behind it.
Same container pattern as concerns: the document says which assessment it is
evidence for instead of hanging loose on the change with a hopeful filename.

Nullable, so every existing attachment stays change-level. The FK lives in the
ORM only (SQLite cannot ADD COLUMN with an FK). Written as its own revision
rather than folded into 054, which has already run.

Revision ID: 055
Revises: 054
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_attachments" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_attachments")}
    if "assessment_id" not in cols:
        op.add_column("change_attachments",
                      sa.Column("assessment_id", sa.Integer(), nullable=True))
        op.create_index("ix_change_attachments_assessment_id",
                        "change_attachments", ["assessment_id"])


def downgrade() -> None:
    pass  # forward-only
