"""068: department-defined risk types.

A department extends its own risk dropdown without a code change. Keys are
namespaced per department; soft-deleted so raised rows keep their key.
Additive, dialect-neutral.

Revision ID: 068
Revises: 067
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "department_risk_types" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "department_risk_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                  nullable=False, index=True),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    pass  # forward-only
