"""048: Project Managers may raise change requests too.

Migration 041 narrowed can_start_change to Sales alone. In practice a PM
fields requests that never pass through Sales, and having them ask Sales to
type it in is bookkeeping, not control. Sales keeps the flag.

Core expression, not raw SQL: can_start_change is a real BOOLEAN on Postgres
and an INTEGER on SQLite.

Revision ID: 048
Revises: 047
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None

_dept = sa.table(
    "wf_departments",
    sa.column("name", sa.String),
    sa.column("can_start_change", sa.Boolean),
)


def _has_flag(bind) -> bool:
    insp = inspect(bind)
    if "wf_departments" not in insp.get_table_names():
        return False
    return "can_start_change" in {c["name"]
                                  for c in insp.get_columns("wf_departments")}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_flag(bind):
        return
    bind.execute(_dept.update()
                 .where(_dept.c.name == "Project Manager")
                 .values(can_start_change=sa.true()))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_flag(bind):
        return
    bind.execute(_dept.update()
                 .where(_dept.c.name == "Project Manager")
                 .values(can_start_change=sa.false()))
