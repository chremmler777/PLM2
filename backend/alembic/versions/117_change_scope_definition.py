"""117: change_requests.scope_definition, the scope of the change in the
project manager's words (written in captured/scoping, read-only afterwards).

Revision ID: 117
Revises: 116
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("change_requests", "scope_definition"):
        with op.batch_alter_table("change_requests") as batch:
            batch.add_column(sa.Column("scope_definition", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("change_requests", "scope_definition"):
        with op.batch_alter_table("change_requests") as batch:
            batch.drop_column("scope_definition")
