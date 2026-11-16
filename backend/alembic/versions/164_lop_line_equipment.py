"""164: a LOP line can be linked to equipment of its project in PLM.

lop_line_equipment links a line to parts rows of category tool, gauge or
assembly_equipment (EOATs are assembly equipment numbered <tool>-1x). The
item itself stays in PLM; the LOP only points at it.

Revision ID: 164
Revises: 163
"""
import sqlalchemy as sa
from alembic import op

revision = "164"
down_revision = "163"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lop_line_equipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("line_id", sa.Integer(), sa.ForeignKey("lop_lines.id"), nullable=False),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("line_id", "part_id", name="uq_lop_line_equipment"),
    )
    op.create_index("ix_lop_line_equipment_line_id", "lop_line_equipment", ["line_id"])
    op.create_index("ix_lop_line_equipment_part_id", "lop_line_equipment", ["part_id"])


def downgrade() -> None:
    op.drop_index("ix_lop_line_equipment_part_id", table_name="lop_line_equipment")
    op.drop_index("ix_lop_line_equipment_line_id", table_name="lop_line_equipment")
    op.drop_table("lop_line_equipment")
