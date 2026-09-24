"""084: colour code (MIC colour of an unpainted article) and grain on parts.

Revision ID: 084
Revises: 083
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None

COLUMNS = [
    ("colour_code", sa.String(40)),
    ("grain", sa.String(80)),
]


def upgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("parts")}
    missing = [(n, t) for n, t in COLUMNS if n not in have]
    if missing:
        with op.batch_alter_table("parts") as batch:
            for name, type_ in missing:
                batch.add_column(sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("parts")}
    present = [n for n, _ in COLUMNS if n in have]
    if present:
        with op.batch_alter_table("parts") as batch:
            for name in present:
                batch.drop_column(name)
