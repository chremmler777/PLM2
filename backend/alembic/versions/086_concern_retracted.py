"""086: retracted_at / retracted_by on change_concerns — a risk deleted by its raiser.

Revision ID: 086
Revises: 085
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None

COLUMNS = [
    ("retracted_at", sa.DateTime()),
    ("retracted_by", sa.Integer()),
]


def upgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("change_concerns")}
    missing = [(n, t) for n, t in COLUMNS if n not in have]
    if missing:
        with op.batch_alter_table("change_concerns") as batch:
            for name, type_ in missing:
                batch.add_column(sa.Column(name, type_, nullable=True))
            if "retracted_by" in {n for n, _ in missing}:
                batch.create_foreign_key(
                    "fk_change_concerns_retracted_by", "users",
                    ["retracted_by"], ["id"])


def downgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("change_concerns")}
    with op.batch_alter_table("change_concerns") as batch:
        if "retracted_by" in have:
            batch.drop_constraint("fk_change_concerns_retracted_by", type_="foreignkey")
            batch.drop_column("retracted_by")
        if "retracted_at" in have:
            batch.drop_column("retracted_at")
