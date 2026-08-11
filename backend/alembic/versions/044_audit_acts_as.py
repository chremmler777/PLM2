"""044: audit_logs records both identities under acts-as.

An admin walking the flow as another department still acts as themselves; an
entry that names only the assumed department is a forged record (spec D5).
`user_id` keeps holding the EFFECTIVE identity so every existing query and the
hash chain are untouched; the two new columns are additive and nullable.

Revision ID: 044
Revises: 043
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "audit_logs" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("audit_logs")}
    # FKs live in the ORM only (SQLite cannot ADD COLUMN with an FK).
    if "acting_as_department_id" not in cols:
        op.add_column("audit_logs",
                      sa.Column("acting_as_department_id", sa.Integer(), nullable=True))
    if "real_user_id" not in cols:
        op.add_column("audit_logs",
                      sa.Column("real_user_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
