"""074: files on SEP work items.

Each SEP work item becomes a file slot so the filled-in forms that exist
today (xlsx, pdf, docx, scans) can be collected before the forms are rebuilt
in the UI. Deletes are soft: the row stays, the blob stays on disk.

Revision ID: 074
Revises: 073
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "sep_item_files" not in tables:
        op.create_table(
            "sep_item_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("item_id", sa.Integer(),
                      sa.ForeignKey("sep_work_items.id"), nullable=False, index=True),
            sa.Column("project_id", sa.Integer(),
                      sa.ForeignKey("projects.id"), nullable=False, index=True),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("content_type", sa.String(100), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "sep_item_files" in set(insp.get_table_names()):
        op.drop_table("sep_item_files")
