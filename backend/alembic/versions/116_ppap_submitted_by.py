"""116: ppap_submissions.submitted_by, so the four-eyes rule on PPAP
approve/reject can tell the submitter from the approver. Existing submitted
rows fall back to created_by in the app; nothing is backfilled.

Revision ID: 116
Revises: 115
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("ppap_submissions", "submitted_by"):
        with op.batch_alter_table("ppap_submissions") as batch:
            batch.add_column(sa.Column("submitted_by", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_ppap_submissions_submitted_by", "users",
                                     ["submitted_by"], ["id"])


def downgrade() -> None:
    if _has_column("ppap_submissions", "submitted_by"):
        with op.batch_alter_table("ppap_submissions") as batch:
            batch.drop_constraint("fk_ppap_submissions_submitted_by", type_="foreignkey")
            batch.drop_column("submitted_by")
