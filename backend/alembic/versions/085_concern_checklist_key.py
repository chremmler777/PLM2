"""085: checklist_key on change_concerns — the checklist row a risk came from.

Revision ID: 085
Revises: 084
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("change_concerns")}
    if "checklist_key" not in have:
        with op.batch_alter_table("change_concerns") as batch:
            batch.add_column(sa.Column("checklist_key", sa.String(120), nullable=True))


def downgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("change_concerns")}
    if "checklist_key" in have:
        with op.batch_alter_table("change_concerns") as batch:
            batch.drop_column("checklist_key")
