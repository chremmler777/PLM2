"""083: material on parts (articles), linked to MaterialDB or marked new.

Revision ID: 083
Revises: 082
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None

COLUMNS = [
    ("material_source", sa.String(20)),
    ("materialdb_id", sa.Integer()),
    ("material_ktx_number", sa.String(20)),
    ("material_label", sa.String(300)),
    ("material_synced_at", sa.DateTime()),
    ("material_new_text", sa.String(500)),
]
INDEX = "ix_parts_materialdb_id"


def upgrade() -> None:
    bind = op.get_bind()
    have = {c["name"] for c in inspect(bind).get_columns("parts")}
    missing = [(n, t) for n, t in COLUMNS if n not in have]
    if missing:
        with op.batch_alter_table("parts") as batch:
            for name, type_ in missing:
                batch.add_column(sa.Column(name, type_, nullable=True))
    if INDEX not in {i["name"] for i in inspect(bind).get_indexes("parts")}:
        op.create_index(INDEX, "parts", ["materialdb_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if INDEX in {i["name"] for i in inspect(bind).get_indexes("parts")}:
        op.drop_index(INDEX, table_name="parts")
    have = {c["name"] for c in inspect(bind).get_columns("parts")}
    present = [n for n, _ in COLUMNS if n in have]
    if present:
        with op.batch_alter_table("parts") as batch:
            for name in present:
                batch.drop_column(name)
