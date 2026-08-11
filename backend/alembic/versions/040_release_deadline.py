"""040: two-phase deadlines — release_due_* group + quoted_at on change_requests.

required_by_* is reinterpreted as the quote deadline (customer-relevant
changes only); release_due_* is the release deadline set at customer
acceptance or internal cost approval. quoted_at freezes the moment the
change reached 'quoted' so the quoted-on-time fact never needs a
changelog query. Spec: docs/superpowers/specs/2026-08-11-two-phase-
change-deadlines-design.md
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("change_requests")}
    if "quoted_at" not in cols:
        op.add_column("change_requests",
                      sa.Column("quoted_at", sa.DateTime(), nullable=True))
    if "release_due_date" not in cols:
        op.add_column("change_requests",
                      sa.Column("release_due_date", sa.DateTime(), nullable=True))
    if "release_due_reason" not in cols:
        op.add_column("change_requests",
                      sa.Column("release_due_reason", sa.Text(), nullable=True))
    if "release_due_set_by" not in cols:
        # FK lives in the ORM only (SQLite cannot ADD COLUMN with FK)
        op.add_column("change_requests",
                      sa.Column("release_due_set_by", sa.Integer(), nullable=True))
    if "release_due_set_at" not in cols:
        op.add_column("change_requests",
                      sa.Column("release_due_set_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
