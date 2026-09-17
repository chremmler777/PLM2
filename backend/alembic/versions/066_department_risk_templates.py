"""066: department risk templates.

A department's pre-written risks (type, severity, wording) it reuses in the
assessment risk form. Soft-deleted so an accidental entry vanishes from the
list without losing the row. Additive, dialect-neutral.

Revision ID: 066
Revises: 065
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "department_risk_templates" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "department_risk_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                  nullable=False, index=True),
        sa.Column("risk_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    pass  # forward-only
