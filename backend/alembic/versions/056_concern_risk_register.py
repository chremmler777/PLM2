"""056: a concern can be a risk, and a risk is typed and rated.

The assessment phase produced two different things through one channel: points
that hold a department's submit, and points that are simply true and have to
travel with the change ("this wall will short-shot"). The second kind was being
written as a needs_info nobody could ever answer. It becomes its own concern
kind — kind='risk' — carrying the two fields a register needs to be countable:
what sort of risk it is, and how bad.

Both nullable: every existing concern row is a legacy kind and keeps them null,
and a risk row is validated at the service boundary rather than by a CHECK
constraint (the vocabulary lives in app/models/change.py, where the API reads it
from, so a database copy of it would be a second source of truth to drift).

Revision ID: 056
Revises: 055
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_concerns" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_concerns")}
    if "risk_type" not in cols:
        op.add_column("change_concerns",
                      sa.Column("risk_type", sa.String(length=40), nullable=True))
    if "severity" not in cols:
        op.add_column("change_concerns",
                      sa.Column("severity", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
