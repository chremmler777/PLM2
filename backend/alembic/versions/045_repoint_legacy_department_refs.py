"""045: repoint every reference off the legacy department rows.

Migration 043 renamed three departments — except on a database that already
held BOTH names (production did). There the rename branch deactivated the old
row instead of colliding on the unique name, which left live references
hanging off a tombstone:

  * a user whose membership sits on the old "R&D" row is not in "Development",
    so impact-confirm authz silently refuses them;
  * a RASIC template row pointing at the deactivated department routes into
    the void when the stage fans out.

So this moves every FK reference from the old row to the new one, per pair.
The old rows survive as deactivated tombstones with zero references — history
that no longer decides anything.

user_departments is the one table needing care: its PK is (user_id,
department_id), so a user sitting in BOTH rows would collide on UPDATE. Those
duplicates are deleted first, the rest are repointed — the same treatment
migration 032 gave its merges.

Everything runs through SQLAlchemy Core so it renders per dialect (Postgres in
production, SQLite in tests). Guarded on both rows existing and on each table
existing, so a partial history upgrades cleanly.

Revision ID: 045
Revises: 044
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None

# (legacy name, current name) — mirrors 043's RENAMES.
PAIRS = [
    ("R&D", "Development"),
    ("Tooling Engineer", "Tool Engineer"),
    ("Planner/Scheduler", "Scheduling"),
]

# Every (table, column) with an FK to wf_departments.id, from the models.
# user_departments is handled separately (composite PK).
REFERENCES = [
    ("wf_step_rasic", "department_id"),
    ("wf_instance_tasks", "department_id"),
    ("change_assessments", "department_id"),
    ("change_concerns", "department_id"),
    ("department_rate", "department_id"),
    ("assessment_activity", "department_id"),
    ("lessons_learned", "department_id"),
    ("audit_logs", "acting_as_department_id"),
]

_dept = sa.table(
    "wf_departments",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)
_user_dept = sa.table(
    "user_departments",
    sa.column("user_id", sa.Integer),
    sa.column("department_id", sa.Integer),
)


def _ref_table(table: str, column: str):
    return sa.table(table, sa.column(column, sa.Integer))


def _dept_id(bind, name):
    return bind.execute(
        sa.select(_dept.c.id).where(_dept.c.name == name)).scalar()


def _move(bind, tables, old_id: int, new_id: int) -> dict:
    """Repoint one pair. Returns rows moved per table."""
    moved = {}

    if "user_departments" in tables:
        # Users already in the target would violate the composite PK.
        dupes = bind.execute(
            sa.select(sa.func.count()).select_from(_user_dept).where(
                _user_dept.c.department_id == old_id,
                _user_dept.c.user_id.in_(
                    sa.select(_user_dept.c.user_id).where(
                        _user_dept.c.department_id == new_id)),
            )).scalar() or 0
        if dupes:
            bind.execute(_user_dept.delete().where(
                _user_dept.c.department_id == old_id,
                _user_dept.c.user_id.in_(
                    sa.select(_user_dept.c.user_id).where(
                        _user_dept.c.department_id == new_id)),
            ))
        res = bind.execute(_user_dept.update()
                           .where(_user_dept.c.department_id == old_id)
                           .values(department_id=new_id))
        moved["user_departments"] = res.rowcount or 0
        moved["user_departments (deduped)"] = dupes

    for table, column in REFERENCES:
        if table not in tables:
            continue
        t = _ref_table(table, column)
        res = bind.execute(t.update()
                           .where(t.c[column] == old_id)
                           .values(**{column: new_id}))
        if res.rowcount:
            moved[f"{table}.{column}"] = res.rowcount
    return moved


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    if "wf_departments" not in tables:
        return
    # audit_logs.acting_as_department_id only exists from 044 onward.
    tables = {t for t in tables
              if t != "audit_logs"
              or "acting_as_department_id" in {c["name"] for c in
                                               insp.get_columns("audit_logs")}}

    for old_name, new_name in PAIRS:
        old_id = _dept_id(bind, old_name)
        new_id = _dept_id(bind, new_name)
        if old_id is None or new_id is None or old_id == new_id:
            continue
        moved = _move(bind, tables, old_id, new_id)
        if moved:
            print(f"045: {old_name} -> {new_name}: {moved}")


def downgrade() -> None:
    pass  # forward-only: the legacy rows are tombstones, not a target
