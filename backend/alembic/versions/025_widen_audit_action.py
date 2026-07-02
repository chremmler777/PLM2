"""Phase D: widen audit_logs.action from String(20) to String(64).

Revision ID: 025
Revises: 024
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"]: c for c in inspect(bind).get_columns("audit_logs")}
    if "action" in cols:
        with op.batch_alter_table("audit_logs") as batch:
            batch.alter_column(
                "action", type_=sa.String(64), existing_type=sa.String(20),
                existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column(
            "action", type_=sa.String(20), existing_type=sa.String(64),
            existing_nullable=False)
