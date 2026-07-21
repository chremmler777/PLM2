"""028: sales-settable required-by deadline on change_requests"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("change_requests")}
    if "required_by_date" not in cols:
        op.add_column("change_requests",
                      sa.Column("required_by_date", sa.DateTime(), nullable=True))
    if "required_by_reason" not in cols:
        op.add_column("change_requests",
                      sa.Column("required_by_reason", sa.Text(), nullable=True))
    if "required_by_set_by" not in cols:
        # FK lives in the ORM only (SQLite cannot ADD COLUMN with FK)
        op.add_column("change_requests",
                      sa.Column("required_by_set_by", sa.Integer(), nullable=True))
    if "required_by_set_at" not in cols:
        op.add_column("change_requests",
                      sa.Column("required_by_set_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    pass  # forward-only, consistent with 023-027
