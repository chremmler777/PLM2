"""041: capture is Sales' job — can_start_change narrowed to Sales.

Migration 032 added wf_departments.can_start_change and seeded it true for
five departments, but nothing ever read the flag. Raising a change is now
gated on it (admin, or a member of a can_start_change department), so the
seeded set has to match the rule we actually want: Sales captures the
request, the project team scopes it.

Forward-only and SQLite-safe: plain UPDATEs, no schema change. Downgrade
restores migration 032's five starter departments.

Revision ID: 041
Revises: 040
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None

# Migration 032's starter set, restored on downgrade.
_032_STARTERS = ["Sales", "Project Manager", "Tool design", "IE", "R&D"]


def _has_flag(bind) -> bool:
    insp = inspect(bind)
    if "wf_departments" not in insp.get_table_names():
        return False
    return "can_start_change" in {c["name"] for c in insp.get_columns("wf_departments")}


# Core expressions, not raw SQL: the flag is a real BOOLEAN on Postgres but an
# INTEGER on SQLite, so literal 0/1 comparisons only work on one of them.
_dept = sa.table(
    "wf_departments",
    sa.column("name", sa.String),
    sa.column("can_start_change", sa.Boolean),
)


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_flag(bind):
        return
    bind.execute(_dept.update().values(can_start_change=sa.false()))
    bind.execute(_dept.update()
                 .where(_dept.c.name == "Sales")
                 .values(can_start_change=sa.true()))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_flag(bind):
        return
    bind.execute(_dept.update().values(can_start_change=sa.false()))
    bind.execute(_dept.update()
                 .where(_dept.c.name.in_(_032_STARTERS))
                 .values(can_start_change=sa.true()))
