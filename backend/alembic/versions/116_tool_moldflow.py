"""116: Moldflow timing per tool.

tool_moldflow: one row per tool, Moldflow version and (optional) cavity
layout, with the input states (geometry, gate, UDB), the step dates
(requested, received, KTX review, sent to customer, customer feedback,
final), an explicit status, blockers, owner, notes and a source reference.
Soft delete (deleted_at). One live row per (tool, version, layout): a
partial unique index over coalesce(cavity_layout, '') so a NULL layout
counts once and a deleted row does not block a new one.

Guarded (a table that exists already is left alone), dialect-neutral.

Revision ID: 116
Revises: 115
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None

UNIQUE = "uq_tool_moldflow_tool_version_layout"


def upgrade() -> None:
    bind = op.get_bind()
    if "tool_moldflow" in set(inspect(bind).get_table_names()):
        return
    op.create_table(
        "tool_moldflow",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tool_part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("version", sa.String(10), nullable=False, server_default="V1"),
        sa.Column("cavity_layout", sa.String(40), nullable=True),
        sa.Column("geometry_status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("gate_status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("udb_status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("material_label", sa.String(120), nullable=True),
        sa.Column("udb_source", sa.String(255), nullable=True),
        sa.Column("mf_requested_on", sa.Date(), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=True),
        sa.Column("ktx_review_on", sa.Date(), nullable=True),
        sa.Column("sent_customer_on", sa.Date(), nullable=True),
        sa.Column("customer_feedback_on", sa.Date(), nullable=True),
        sa.Column("final_on", sa.Date(), nullable=True),
        sa.Column("customer_feedback", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("blockers", sa.Text(), nullable=True),
        sa.Column("owner", sa.String(120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_tool_moldflow_tool_part_id", "tool_moldflow", ["tool_part_id"])
    # Expression + partial index: plain SQL, the same on PostgreSQL and SQLite.
    bind.execute(sa.text(
        f"CREATE UNIQUE INDEX {UNIQUE} ON tool_moldflow "
        "(tool_part_id, version, COALESCE(cavity_layout, '')) WHERE deleted_at IS NULL"))


def downgrade() -> None:
    if "tool_moldflow" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("tool_moldflow")
