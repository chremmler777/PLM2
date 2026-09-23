"""079: part thumbnail (thumbnail_path, thumbnail_updated_at on parts).

Revision ID: 079
Revises: 078
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("parts")}
    with op.batch_alter_table("parts") as batch:
        if "thumbnail_path" not in cols:
            batch.add_column(sa.Column("thumbnail_path", sa.String(500), nullable=True))
        if "thumbnail_updated_at" not in cols:
            batch.add_column(sa.Column("thumbnail_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("parts")}
    with op.batch_alter_table("parts") as batch:
        if "thumbnail_updated_at" in cols:
            batch.drop_column("thumbnail_updated_at")
        if "thumbnail_path" in cols:
            batch.drop_column("thumbnail_path")
