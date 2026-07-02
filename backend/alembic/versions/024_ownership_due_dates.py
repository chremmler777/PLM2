"""Phase C: owner_id/accepted_at/due_date on wf_instance_tasks and
change_assessments.

Revision ID: 024
Revises: 023
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None

# SQLite cannot ADD COLUMN with a FK constraint (see migration 023's note):
# owner_id ships as a plain Integer here; the ORM model carries the ForeignKey.
_TABLES = ("wf_instance_tasks", "change_assessments")


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        insp = inspect(bind)
        cols = {c["name"] for c in insp.get_columns(table)}
        if "owner_id" not in cols:
            op.add_column(table, sa.Column("owner_id", sa.Integer(), nullable=True))
        if "accepted_at" not in cols:
            op.add_column(table, sa.Column("accepted_at", sa.DateTime(), nullable=True))
        if "due_date" not in cols:
            op.add_column(table, sa.Column("due_date", sa.DateTime(), nullable=True))
        indexes = {ix["name"] for ix in inspect(bind).get_indexes(table)}
        ix_name = f"ix_{table}_owner_id"
        if ix_name not in indexes:
            op.create_index(ix_name, table, ["owner_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        indexes = {ix["name"] for ix in inspect(bind).get_indexes(table)}
        ix_name = f"ix_{table}_owner_id"
        if ix_name in indexes:
            op.drop_index(ix_name, table_name=table)
        op.drop_column(table, "owner_id")
        op.drop_column(table, "accepted_at")
        op.drop_column(table, "due_date")
