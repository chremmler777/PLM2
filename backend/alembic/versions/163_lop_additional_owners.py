"""163: additional owners on LOP lines.

The main owner stays lop_lines.responsible_id (department, lateness and
escalation are that person's). lop_line_owners names more people who own the
line with them: it shows as theirs and they can report it done.

Revision ID: 163
Revises: 162
"""
import sqlalchemy as sa
from alembic import op

revision = "163"
down_revision = "162"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lop_line_owners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("lop_lines.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("line_id", "user_id", name="uq_lop_line_owner"),
    )
    op.create_index("ix_lop_line_owners_line_id", "lop_line_owners", ["line_id"])
    op.create_index("ix_lop_line_owners_user_id", "lop_line_owners", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_lop_line_owners_user_id", table_name="lop_line_owners")
    op.drop_index("ix_lop_line_owners_line_id", table_name="lop_line_owners")
    op.drop_table("lop_line_owners")
