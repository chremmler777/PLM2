"""146: open assessments owed by a retired department move to its successor
(click-through R38; R25 inactive departments grant nothing, R31 in-flight
changes keep working).

Migration 043 retired Developer and folded R&D, Tooling Engineer and
Planner/Scheduler into Development, Tool Engineer and Scheduling. A change
routed before that still carried an open row of the retired department
(local CR-2026-0022: 'Developer', 3 days overdue): nobody can be a member of
a retired department, so nobody could answer it. Routing has refused retired
departments since (ChangeRoutingService._drop_unroutable / apply_deviation);
this moves the rows already there.

Data
  change_assessments: an open row (not submitted, not waived) of a retired
  department whose successor is active moves to the successor, together with
  its linked engine task while that task is still active. Skipped: answered
  rows and rows whose task is already approved or waived (history), retired departments without a successor (Logistics,
  Production, ...), and a change whose successor already holds a row in the
  same stage (one department, one row per stage).

Repeatable. Downgrade is a no-op: the old owner could not answer anyway.

Revision ID: 146
Revises: 145
"""
import sqlalchemy as sa
from alembic import op

revision = "146"
down_revision = "145"
branch_labels = None
depends_on = None

# retired name -> the active department that does its work now (043)
SUCCESSORS = {
    "Developer": "Development",
    "R&D": "Development",
    "Tooling Engineer": "Tool Engineer",
    "Planner/Scheduler": "Scheduling",
}


def upgrade() -> None:
    bind = op.get_bind()
    depts = {name: (did, bool(active)) for did, name, active in bind.execute(
        sa.text("SELECT id, name, is_active FROM wf_departments")).all()}
    for old, new in SUCCESSORS.items():
        if old not in depts or new not in depts:
            continue
        old_id, old_active = depts[old]
        new_id, new_active = depts[new]
        if old_active or not new_active:
            continue
        rows = bind.execute(sa.text(
            "SELECT id, change_id, stage_order, wf_instance_task_id "
            "FROM change_assessments WHERE department_id = :d "
            "AND submitted_at IS NULL "
            "AND (status IS NULL OR status NOT IN ('submitted', 'waived'))"),
            {"d": old_id}).all()
        for aid, change_id, stage, task_id in rows:
            taken = bind.execute(sa.text(
                "SELECT 1 FROM change_assessments WHERE change_id = :c "
                "AND department_id = :d AND stage_order = :s"),
                {"c": change_id, "d": new_id, "s": stage}).first()
            if taken:
                continue
            if task_id is not None:
                # the row reads its state through the task: a task already
                # approved or waived is a finished answer (history)
                state = bind.execute(sa.text(
                    "SELECT status FROM wf_instance_tasks WHERE id = :t"),
                    {"t": task_id}).scalar()
                if state not in (None, "active"):
                    continue
            bind.execute(sa.text(
                "UPDATE change_assessments SET department_id = :d WHERE id = :a"),
                {"d": new_id, "a": aid})
            if task_id is not None:
                bind.execute(sa.text(
                    "UPDATE wf_instance_tasks SET department_id = :d "
                    "WHERE id = :t AND department_id = :old AND status = 'active'"),
                    {"d": new_id, "t": task_id, "old": old_id})


def downgrade() -> None:
    pass
