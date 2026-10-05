"""112: tool shrinkage decision record.

tool_shrink_decisions: per tool, which shrinkage the steel is cut with, its source (datasheet,
supplier statement, KTX tool experience, own value), the candidates shown at the time, the
rationale and who decided; after the trial the measured shrinkage, verdict, note for the next
tool and the report status to MaterialDB.

Guarded (a table that exists already is left alone), dialect-neutral.

Revision ID: 112
Revises: 111
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "112"
down_revision = "111"
branch_labels = None
depends_on = None

TABLE = "tool_shrink_decisions"


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE in set(inspect(bind).get_table_names()):
        return
    pct = sa.Numeric(5, 3)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tool_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="current"),
        sa.Column("parallel_pct", pct, nullable=False),
        sa.Column("normal_pct", pct, nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_label", sa.String(500), nullable=True),
        sa.Column("materialdb_id", sa.Integer(), nullable=True),
        sa.Column("material_label", sa.String(300), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("measured_parallel_pct", pct, nullable=True),
        sa.Column("measured_normal_pct", pct, nullable=True),
        sa.Column("measured_ref", sa.String(300), nullable=True),
        sa.Column("verdict", sa.String(10), nullable=True),
        sa.Column("next_time_note", sa.Text(), nullable=True),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("feedback_status", sa.String(10), nullable=True),
        sa.Column("feedback_error", sa.String(500), nullable=True),
        sa.Column("feedback_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tool_shrink_decisions_tool_id", TABLE, ["tool_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE in set(inspect(bind).get_table_names()):
        op.drop_table(TABLE)
