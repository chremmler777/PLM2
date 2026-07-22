"""032: Change-starter departments — merge duplicates, retire dead seeds,
add wf_departments.can_start_change.

- Tool Engineer -> Tool design, Manufacturing Engineer -> IE. Both duplicates
  are seed-era names; the targets carry the real RASIC/rate/activity rows.
- Retires Developer, Tool Engineer, Manufacturing Engineer, APQP and
  Operations Manager (is_active=false). Their only RASIC rows sit on
  wf_templates id 1 ("ECR"), which no change_routing_standards row points at,
  so no live routing is affected.
- can_start_change seeded true for Sales, Project Manager, Tool design, IE, R&D.

The merge is deliberately NOT reversed on downgrade: the duplicate rows held
no unique data, so re-splitting them would be guesswork.

Revision ID: 032
Revises: 031
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None

MERGES = [("Tool Engineer", "Tool design"), ("Manufacturing Engineer", "IE")]
RETIRE = ["Developer", "Tool Engineer", "Manufacturing Engineer",
          "APQP", "Operations Manager"]
STARTERS = ["Sales", "Project Manager", "Tool design", "IE", "R&D"]

# Every table with an FK to wf_departments.
REPOINT_TABLES = [
    "wf_step_rasic", "lessons_learned", "change_assessments",
    "department_rate", "assessment_activity", "wf_instance_tasks",
]


def _dept_id(bind, name):
    return bind.execute(
        sa.text("SELECT id FROM wf_departments WHERE name = :n"), {"n": name}
    ).scalar()


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("wf_departments")}
    if "can_start_change" not in cols:
        op.add_column(
            "wf_departments",
            sa.Column("can_start_change", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
        )

    tables = set(insp.get_table_names())

    for dup_name, target_name in MERGES:
        dup = _dept_id(bind, dup_name)
        target = _dept_id(bind, target_name)
        if dup is None or target is None or dup == target:
            continue

        for table in REPOINT_TABLES:
            if table not in tables:
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET department_id = :t "
                        f"WHERE department_id = :d"),
                {"t": target, "d": dup},
            )

        # user_departments has PK (user_id, department_id): a user in BOTH the
        # duplicate and the target would collide on UPDATE. Drop the duplicate
        # row for those users, repoint the rest.
        if "user_departments" in tables:
            bind.execute(
                sa.text(
                    "DELETE FROM user_departments WHERE department_id = :d "
                    "AND user_id IN (SELECT user_id FROM user_departments "
                    "WHERE department_id = :t)"
                ),
                {"d": dup, "t": target},
            )
            bind.execute(
                sa.text("UPDATE user_departments SET department_id = :t "
                        "WHERE department_id = :d"),
                {"t": target, "d": dup},
            )

    for name in RETIRE:
        bind.execute(
            sa.text("UPDATE wf_departments SET is_active = false WHERE name = :n"),
            {"n": name},
        )

    for name in STARTERS:
        bind.execute(
            sa.text("UPDATE wf_departments SET can_start_change = true WHERE name = :n"),
            {"n": name},
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    for name in RETIRE:
        bind.execute(
            sa.text("UPDATE wf_departments SET is_active = true WHERE name = :n"),
            {"n": name},
        )

    cols = {c["name"] for c in insp.get_columns("wf_departments")}
    if "can_start_change" in cols:
        op.drop_column("wf_departments", "can_start_change")
