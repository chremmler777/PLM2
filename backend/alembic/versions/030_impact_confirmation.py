"""030: Task 18 - Engineering (R&D) owns the affected-items decision.

Adds nullable impact_confirmed_by / impact_confirmed_at columns on
change_requests. Both are set together by POST /changes/{id}/impact/confirm
and cleared together whenever the impacted-item set changes afterwards
(re-confirmation required). in_implementation's soft-block guard reads
impact_confirmed_at.

Revision ID: 030
Revises: 029
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("change_requests")}
    if "impact_confirmed_by" not in cols:
        op.add_column("change_requests",
                      sa.Column("impact_confirmed_by", sa.Integer(), nullable=True))
    if "impact_confirmed_at" not in cols:
        op.add_column("change_requests",
                      sa.Column("impact_confirmed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    pass  # forward-only, consistent with 023-029
