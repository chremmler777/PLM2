"""091: change_actual_costs (P&L offer versus doing, spec §13).

One row per actual cost of a change that is not booked hours: supplier
invoice lines, scrap, other. Dialect-neutral, same file on Postgres and
SQLite.

Revision ID: 091
Revises: 090
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "change_actual_costs" in set(inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "change_actual_costs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"),
                  nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                  nullable=True),
        sa.Column("category", sa.String(12), nullable=False,
                  server_default="external"),
        sa.Column("vendor_name", sa.String(120), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("cost_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("attachment_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_change_actual_costs_change_id", "change_actual_costs",
                    ["change_id"])


def downgrade() -> None:
    op.drop_index("ix_change_actual_costs_change_id", table_name="change_actual_costs")
    op.drop_table("change_actual_costs")
