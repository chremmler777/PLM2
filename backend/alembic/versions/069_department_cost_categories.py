"""069: department-defined cost categories.

A department extends its own costing category list without a code change;
each category is typed money or time. Soft-deleted. Additive, dialect-neutral.

Revision ID: 069
Revises: 068
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "department_cost_categories" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "department_cost_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                  nullable=False, index=True),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("entry_type", sa.String(10), nullable=False, server_default="money"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    pass  # forward-only
