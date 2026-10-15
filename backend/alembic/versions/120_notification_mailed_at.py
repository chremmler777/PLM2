"""120: a notification is mailed at most once (ECR-solid spec §0 Notifications).

Schema
  notifications.mailed_at   when the mail copy went out (or was skipped);
                            NULL = not yet (app/services/mail_outbox.py).

Data
  every existing notification is stamped mailed (at its creation time), so
  switching SMTP on never mails the backlog.

Repeatable: the column is added once; the backfill only fills NULLs.

Revision ID: 120
Revises: 119
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "120"
down_revision = "119"
branch_labels = None
depends_on = None

TABLE = "notifications"
COLUMN = "mailed_at"
INDEX = "ix_notifications_mailed_at"


def _columns() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    if COLUMN not in _columns():
        op.add_column(TABLE, sa.Column(COLUMN, sa.DateTime(), nullable=True))
        op.create_index(INDEX, TABLE, [COLUMN])
    op.execute(f"UPDATE {TABLE} SET {COLUMN} = created_at WHERE {COLUMN} IS NULL")


def downgrade() -> None:
    if COLUMN in _columns():
        op.drop_index(INDEX, table_name=TABLE)
        op.drop_column(TABLE, COLUMN)
