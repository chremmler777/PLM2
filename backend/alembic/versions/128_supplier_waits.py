"""128: waiting on a supplier (ECR-solid spec §4 / §5 / §8, C23, C25).

Schema
  supplier_waits      one row per wait: change, department, phase
                      (costing | implementation), vendor, asked_on,
                      expected_by, the costing position it prices
                      (optional), note; closed_at / closed_by /
                      close_reason (received | price_on_estimate |
                      not_needed) when it ends

Data: none. "<Dept> has no cost" (C18) is stored on the department's
assessment row (details.costing_no_cost) like its finalization, no column.

Repeatable: the table is created once.

Revision ID: 128
Revises: 127
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "128"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "supplier_waits" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "supplier_waits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"),
                  nullable=False, index=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                  nullable=False),
        sa.Column("phase", sa.String(20), nullable=False, server_default="costing"),
        sa.Column("vendor_name", sa.String(120), nullable=False),
        sa.Column("asked_on", sa.Date(), nullable=False),
        sa.Column("expected_by", sa.Date(), nullable=False),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("costing_positions.id"),
                  nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("close_reason", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    if "supplier_waits" in inspect(op.get_bind()).get_table_names():
        op.drop_table("supplier_waits")
