"""162: LOP lines get a details text and attached files.

lop_lines.details holds the PM's longer text under the title (goal, steps,
done-when); the title stays one short line (500 characters). lop_files is one
row per attached file, soft-deleted, blob under uploads/lop/<project>/<line>/.

Revision ID: 162
Revises: 161
"""
import sqlalchemy as sa
from alembic import op

revision = "162"
down_revision = "161"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lop_lines", sa.Column("details", sa.Text(), nullable=True))
    op.create_table(
        "lop_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("lop_lines.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("stored_path", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_lop_files_line_id", "lop_files", ["line_id"])
    op.create_index("ix_lop_files_project_id", "lop_files", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_lop_files_project_id", table_name="lop_files")
    op.drop_index("ix_lop_files_line_id", table_name="lop_files")
    op.drop_table("lop_files")
    op.drop_column("lop_lines", "details")
