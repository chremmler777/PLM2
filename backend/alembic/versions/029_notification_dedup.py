"""029: notification dedup - kind + subject_key columns and index"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("notifications")}
    if "kind" not in cols:
        op.add_column("notifications",
                      sa.Column("kind", sa.String(40), nullable=True))
    if "subject_key" not in cols:
        op.add_column("notifications",
                      sa.Column("subject_key", sa.String(120), nullable=True))

    indexes = {ix["name"] for ix in insp.get_indexes("notifications")}
    if "ix_notifications_dedup" not in indexes:
        op.create_index(
            "ix_notifications_dedup", "notifications",
            ["user_id", "kind", "subject_key"])


def downgrade() -> None:
    pass  # forward-only, consistent with 023-028
