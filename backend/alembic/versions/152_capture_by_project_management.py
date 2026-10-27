"""152: capturing a change is Project Management's job (Christoph 2026-10-26,
"important").

Project Management is the process owner (D2: the project's lead PM leads
every change) and now also captures every customer change. Sales no longer
starts or captures changes; it stays the customer contact (quote deadline,
offer, customer answer, rejection letter). The change's Sales contact is the
project's Sales responsible (project team), else its named backup, else a
Sales member Project Management picks (ChangeService.default_sales_owner_id).

Data (wf_departments)
  Sales  can_start_change -> false. Project Manager keeps true (migration
         048). Internal starters (can_start_internal_change: Development,
         Process / Tool / Manufacturing Engineer) are untouched, and so is
         every existing change (raiser, Sales contact and lead stay).

Core expression, not raw SQL: can_start_change is a real BOOLEAN on Postgres
and an INTEGER on SQLite. Repeatable. Downgrade gives Sales the flag back.

Revision ID: 152
Revises: 151
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "152"
down_revision = "151"
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


def _set_sales(value) -> None:
    bind = op.get_bind()
    if not _has_flag(bind):
        return
    bind.execute(_dept.update()
                 .where(_dept.c.name == "Sales")
                 .values(can_start_change=value))


def upgrade() -> None:
    _set_sales(sa.false())


def downgrade() -> None:
    _set_sales(sa.true())
