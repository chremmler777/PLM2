"""043: ECR role cleanup — renames, Packaging Engineer, non-ECR deactivation.

The department list still carried seed-era names and a long tail of roles that
never take part in an ECR. This settles it:

  renames      R&D -> Development, Tooling Engineer -> Tool Engineer,
               Planner/Scheduler -> Scheduling
  created      Packaging Engineer (action)
  active       the ECR nine (Sales, Project Manager, APQP, Tool Engineer,
               Manufacturing Engineer, Process Engineer, Development,
               Scheduling, Packaging Engineer) + Quality, which co-signs
               approvals
  deactivated  Logistics, Production, Purchasing, Production control,
               Operations Manager, Developer

Every statement goes through SQLAlchemy Core, never raw SQL with 0/1: is_active
is a real BOOLEAN on Postgres and an INTEGER on SQLite, and literal integers
only work on one of them.

Existing rows are matched by their CURRENT name and skipped when absent, so the
migration is safe on a database that only ever saw part of the history. A
rename whose target name already exists deactivates the stale source row
instead of colliding on it.

Revision ID: 043
Revises: 042
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None

RENAMES = [
    ("R&D", "Development"),
    ("Tooling Engineer", "Tool Engineer"),
    ("Planner/Scheduler", "Scheduling"),
]

# ECR order first, then Quality, then everything retired below.
ECR_ORDER = [
    "Sales", "Project Manager", "APQP", "Tool Engineer",
    "Manufacturing Engineer", "Process Engineer", "Development",
    "Scheduling", "Packaging Engineer",
]
CO_SIGNER = "Quality"
DEACTIVATE = [
    "Logistics", "Production", "Purchasing", "Production control",
    "Operations Manager", "Developer",
]

_dept = sa.table(
    "wf_departments",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("flow_type", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
    sa.column("can_start_change", sa.Boolean),
    sa.column("created_at", sa.DateTime),
)


def _names(bind) -> dict:
    """name -> id for every existing department."""
    return {n: i for (i, n) in bind.execute(
        sa.select(_dept.c.id, _dept.c.name)).all()}


def upgrade() -> None:
    bind = op.get_bind()
    if "wf_departments" not in inspect(bind).get_table_names():
        return

    existing = _names(bind)
    for old, new in RENAMES:
        if old not in existing:
            continue
        if new in existing:
            # Target already taken (a partial history, or a re-run): retire the
            # stale source row rather than colliding on the name.
            bind.execute(_dept.update()
                         .where(_dept.c.name == old)
                         .values(is_active=sa.false()))
            continue
        bind.execute(_dept.update()
                     .where(_dept.c.name == old).values(name=new))
        existing[new] = existing.pop(old)

    if "Packaging Engineer" not in existing:
        bind.execute(_dept.insert().values(
            name="Packaging Engineer", flow_type="action",
            is_active=sa.true(), can_start_change=sa.false(),
            sort_order=len(ECR_ORDER), created_at=datetime.utcnow()))
        existing = _names(bind)

    # The ECR set (and Quality) are the active roster, in order.
    for order, name in enumerate(ECR_ORDER + [CO_SIGNER], start=1):
        if name in existing:
            bind.execute(_dept.update().where(_dept.c.name == name).values(
                is_active=sa.true(), sort_order=order))

    # Everything else steps out of the way, sorted after the active roster.
    base = len(ECR_ORDER) + 1
    for offset, name in enumerate(DEACTIVATE, start=1):
        if name in existing:
            bind.execute(_dept.update().where(_dept.c.name == name).values(
                is_active=sa.false(), sort_order=base + offset))


def downgrade() -> None:
    pass  # forward-only
