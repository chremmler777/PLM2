"""150: department membership comes from AdminPanel (Christoph 2026-10-26).

The hub role model: a person is a member of a PLM department because the
AdminPanel token carries that department's plm2 role. PLM no longer edits
memberships; app/dependencies/auth.py syncs user_departments of hub
accounts to the token on login (app/services/hub_departments.py).

Schema (wf_departments)
  hub_role  String(64), unique, nullable: the AdminPanel role (system
            "plm2") that makes a member. NULL = no hub role mapped (retired
            legacy departments; the Departments page warns for an active one).

Data
  1. hub_role by department name (the 13 roles on AdminPanel since
     2026-10-26): Sales plm2_Sales, Project Manager plm2_ProjectManager,
     APQP plm2_APQP, Tool Engineer plm2_ToolEngineer, Manufacturing Engineer
     plm2_ManufacturingEngineer, Process Engineer plm2_ProcessEngineer,
     Logistics plm2_Logistics, Development plm2_Development, Packaging
     Engineer plm2_PackagingEngineer, Quality plm2_Quality, Toolshop
     plm2_Toolshop, Finance plm2_Finance, Management plm2_Management. A
     mapped department is active (Finance and Toolshop have members and
     managers). A name that does not exist is skipped.
  2. Scheduling is Logistics (one department; plm2_Scheduling was deleted
     on AdminPanel): every row that references Scheduling through a foreign
     key to wf_departments (RASIC rows, engine tasks, assessments, cost
     sheet rows, project team, ...) moves to Logistics; a row that would
     duplicate a Logistics row (same unique key, or a RASIC row on a step
     Logistics already has) is dropped instead. Scheduling is deactivated
     and gets no hub role. Department ids inside JSON lists (meeting
     selections, snapshots) are history and stay.
  3. Placeholder / local accounts (admin, testuser, chris, ..., any user
     whose hashed_password is not the hub sentinel "!") are no department
     members: their user_departments rows are deleted (prod has admin,
     testuser and chris rows). Being admin never implies membership.

Repeatable. Downgrade drops hub_role and reactivates Scheduling; moved and
deleted rows stay as they are (no record of them is kept).

Revision ID: 150
Revises: 149
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "150"
down_revision = "149"
branch_labels = None
depends_on = None

TABLE = "wf_departments"
UNIQUE = "uq_wf_departments_hub_role"
HUB_ROLES = {
    "Sales": "plm2_Sales",
    "Project Manager": "plm2_ProjectManager",
    "APQP": "plm2_APQP",
    "Tool Engineer": "plm2_ToolEngineer",
    "Manufacturing Engineer": "plm2_ManufacturingEngineer",
    "Process Engineer": "plm2_ProcessEngineer",
    "Logistics": "plm2_Logistics",
    "Development": "plm2_Development",
    "Packaging Engineer": "plm2_PackagingEngineer",
    "Quality": "plm2_Quality",
    "Toolshop": "plm2_Toolshop",
    "Finance": "plm2_Finance",
    "Management": "plm2_Management",
}
OLD, NEW = "Scheduling", "Logistics"


def _dept_id(bind, name):
    return bind.execute(sa.text(f"SELECT id FROM {TABLE} WHERE name = :n"),
                        {"n": name}).scalar()


def _merge(bind, old_id: int, new_id: int) -> None:
    insp = inspect(bind)
    for table in insp.get_table_names():
        if table == TABLE:
            continue
        cols = [c for fk in insp.get_foreign_keys(table)
                if fk.get("referred_table") == TABLE for c in fk["constrained_columns"]]
        if not cols:
            continue
        keys = [u["column_names"] for u in insp.get_unique_constraints(table)]
        keys += [i["column_names"] for i in insp.get_indexes(table) if i.get("unique")]
        pk = insp.get_pk_constraint(table).get("constrained_columns") or []
        if pk:
            keys.append(pk)
        if table == "wf_step_rasic":
            keys.append(["step_id", "department_id"])   # one RASIC row per step and department
        for col in cols:
            for key in keys:
                # an expression index names no column (None): no key to match
                if col not in key or any(k is None for k in key):
                    continue
                others = [k for k in key if k != col]
                same = " AND ".join([f"n.{col} = :new"] + [f"n.{k} IS NOT DISTINCT FROM o.{k}" for k in others])
                bind.execute(sa.text(
                    f"DELETE FROM {table} o WHERE o.{col} = :old AND EXISTS "
                    f"(SELECT 1 FROM {table} n WHERE {same})"), {"old": old_id, "new": new_id})
            bind.execute(sa.text(f"UPDATE {table} SET {col} = :new WHERE {col} = :old"),
                         {"old": old_id, "new": new_id})


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns(TABLE)}
    if "hub_role" not in cols:
        op.add_column(TABLE, sa.Column("hub_role", sa.String(64), nullable=True))
        op.create_unique_constraint(UNIQUE, TABLE, ["hub_role"])
    old_id, new_id = _dept_id(bind, OLD), _dept_id(bind, NEW)
    if old_id is not None and new_id is not None:
        _merge(bind, old_id, new_id)
        bind.execute(sa.text(f"UPDATE {TABLE} SET is_active = false, hub_role = NULL WHERE id = :i"),
                     {"i": old_id})
    for name, role in HUB_ROLES.items():
        bind.execute(sa.text(f"UPDATE {TABLE} SET hub_role = NULL WHERE hub_role = :r AND name <> :n"),
                     {"r": role, "n": name})
        bind.execute(sa.text(f"UPDATE {TABLE} SET hub_role = :r, is_active = true WHERE name = :n"),
                     {"r": role, "n": name})
    bind.execute(sa.text(
        "DELETE FROM user_departments WHERE user_id IN "
        "(SELECT id FROM users WHERE hashed_password IS DISTINCT FROM '!')"))


def downgrade() -> None:
    bind = op.get_bind()
    if "hub_role" in {c["name"] for c in inspect(bind).get_columns(TABLE)}:
        if UNIQUE in {u["name"] for u in inspect(bind).get_unique_constraints(TABLE)}:
            op.drop_constraint(UNIQUE, TABLE, type_="unique")
        op.drop_column(TABLE, "hub_role")
    bind.execute(sa.text(f"UPDATE {TABLE} SET is_active = true WHERE name = :n"), {"n": OLD})
