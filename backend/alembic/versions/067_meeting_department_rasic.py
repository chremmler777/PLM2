"""067: the scoping meeting records a RASIC letter per department.

Who is Responsible / Accountable / Supports / Consulted on this change is the
room's call, made by the PM with the team — attendance neither grants nor
removes it. Stored as {department_id: letter} next to the id list older
meetings carry. Additive, dialect-neutral.

Revision ID: 067
Revises: 066
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if "change_meetings" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_meetings")}
    if "department_rasic" not in cols:
        op.add_column("change_meetings",
                      sa.Column("department_rasic", sa.JSON(), nullable=True))


def downgrade() -> None:
    pass  # forward-only
