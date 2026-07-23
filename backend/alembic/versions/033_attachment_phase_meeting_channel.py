"""033: attachment baseline freeze + scoping decision channel.

- change_attachments.phase ('baseline' | 'post_scoping'): documents uploaded
  during capture/scoping are the baseline a decision is made on; they freeze
  once the change leaves scoping. Later documents are 'post_scoping'. Existing
  rows default to 'baseline'.
- change_meetings.channel ('meeting' | 'chat' | 'email'): how the scoping
  decision was communicated. The record itself is the VDA/IATF-traceable proof;
  no attached evidence is required. Existing rows default to 'meeting'.

Revision ID: 033
Revises: 032
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def _has_col(insp, table, col):
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if not _has_col(insp, "change_attachments", "phase"):
        op.add_column("change_attachments", sa.Column(
            "phase", sa.String(20), nullable=False, server_default="baseline"))
    if not _has_col(insp, "change_meetings", "channel"):
        op.add_column("change_meetings", sa.Column(
            "channel", sa.String(20), nullable=False, server_default="meeting"))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if _has_col(insp, "change_meetings", "channel"):
        op.drop_column("change_meetings", "channel")
    if _has_col(insp, "change_attachments", "phase"):
        op.drop_column("change_attachments", "phase")
