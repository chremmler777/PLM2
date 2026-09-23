"""078: DFM archive tables (dfm_topics, dfm_entries, dfm_entry_files).

Revision ID: 078
Revises: 077
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "dfm_topics" not in tables:
        op.create_table(
            "dfm_topics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tool_part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("opened_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("opened_at", sa.DateTime(), nullable=False),
            sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_dfm_topics_tool_part_id", "dfm_topics", ["tool_part_id"])
    if "dfm_entries" not in tables:
        op.create_table(
            "dfm_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("dfm_topics.id"), nullable=False),
            sa.Column("party", sa.String(20), nullable=False),
            sa.Column("addressed_to", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("supersedes_id", sa.Integer(), sa.ForeignKey("dfm_entries.id"), nullable=True),
            sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.Date(), nullable=True),
        )
        op.create_index("ix_dfm_entries_topic_id", "dfm_entries", ["topic_id"])
    if "dfm_entry_files" not in tables:
        op.create_table(
            "dfm_entry_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entry_id", sa.Integer(), sa.ForeignKey("dfm_entries.id"), nullable=False),
            sa.Column("original_filename", sa.String(255), nullable=False),
            sa.Column("saved_filename", sa.String(255), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("content_type", sa.String(100), nullable=False),
            sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_dfm_entry_files_entry_id", "dfm_entry_files", ["entry_id"])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name in ("dfm_entry_files", "dfm_entries", "dfm_topics"):
        if name in tables:
            op.drop_table(name)
