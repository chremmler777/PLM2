"""133: the scope change card (ECR-solid §6 [R3]).

Schema
  change_scope_changes   one row per "the customer wants to add or change
                         something" (from quoted on), a recheck effect at
                         quoted or later (customer index) or a PO that
                         differs at acceptance; see app/models/change_scope.py

Data: none. A change flagged scope_changed_after_quote before the card
(legacy, in flight) keeps the old rule: a newer offer or an approved
override covers it.

Repeatable: the table is created once.

Revision ID: 133
Revises: 132
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "133"
down_revision = "132"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "change_scope_changes" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "change_scope_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"),
                  nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="customer"),
        sa.Column("status", sa.String(12), nullable=False, server_default="requested"),
        sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column("what", sa.Text(), nullable=False),
        sa.Column("expects_by", sa.Date(), nullable=True),
        sa.Column("evidence_ref", sa.String(255), nullable=True),
        sa.Column("attachment_id", sa.Integer(), nullable=True),
        sa.Column("post_accept", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("department_ids", sa.JSON(), nullable=True),
        sa.Column("departments_done", sa.JSON(), nullable=True),
        sa.Column("recost_due", sa.Date(), nullable=True),
        sa.Column("offer_id", sa.Integer(), nullable=True),
        sa.Column("new_change_id", sa.Integer(), nullable=True),
        sa.Column("recheck_id", sa.Integer(), nullable=True),
        sa.Column("told_ref", sa.String(255), nullable=True),
        sa.Column("told_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("told_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if "change_scope_changes" in inspect(op.get_bind()).get_table_names():
        op.drop_table("change_scope_changes")
