"""081: DFM audit trail (dfm_audit_events) and dfm_entry_files.sha256.

Append-only events per tool: topic opened / closed / reopened, entry recorded
/ updated, file attached / downloaded / viewed. The data step backfills events
from existing topics, entries and files when the audit table is empty
(app/services/dfm_audit_backfill.py, SQLAlchemy Core only).

Revision ID: 081
Revises: 080
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None

TABLE = "dfm_audit_events"
INDEXES = {
    "ix_dfm_audit_events_tool_part_id": ["tool_part_id"],
    "ix_dfm_audit_events_topic_id": ["topic_id"],
    "ix_dfm_audit_events_at": ["at"],
}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    if "dfm_topics" not in tables:
        return
    if TABLE not in tables:
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tool_part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("dfm_topics.id"), nullable=True),
            sa.Column("entry_id", sa.Integer(), sa.ForeignKey("dfm_entries.id"), nullable=True),
            sa.Column("file_id", sa.Integer(), sa.ForeignKey("dfm_entry_files.id"), nullable=True),
            sa.Column("action", sa.String(40), nullable=False),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("at", sa.DateTime(), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
        )
    existing = {i["name"] for i in inspect(bind).get_indexes(TABLE)}
    for name, cols in INDEXES.items():
        if name not in existing:
            op.create_index(name, TABLE, cols)

    if "sha256" not in {c["name"] for c in insp.get_columns("dfm_entry_files")}:
        with op.batch_alter_table("dfm_entry_files") as batch:
            batch.add_column(sa.Column("sha256", sa.String(64), nullable=True))

    from app.services.dfm_audit_backfill import backfill_dfm_audit
    backfill_dfm_audit(bind)


def downgrade() -> None:
    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if TABLE in tables:
        op.drop_table(TABLE)
    if "dfm_entry_files" in tables and "sha256" in {c["name"] for c in insp.get_columns("dfm_entry_files")}:
        with op.batch_alter_table("dfm_entry_files") as batch:
            batch.drop_column("sha256")
