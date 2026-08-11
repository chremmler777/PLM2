"""034: technical-assessment routing — focused R/I matrix for stage 1.

The ECM Assessment template's stage 1 ("Department assessment") made nine
departments Responsible ("everyone assesses"). Narrow it to the technical
disciplines who each assess their own scope, with support functions Informed:

  R: R&D, Tool design, IE, Process Engineer, APQP, Quality
  I: Logistics, Project Manager, Sales

Also: create the new "Process Engineer" department and reactivate "APQP"
(wrongly retired by migration 032 — it's a real assessor).

Stages 2-3 (Summation & Budget, Customer activities) are unchanged.

Revision ID: 034
Revises: 033
"""
from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None

TEMPLATE = "ECM Assessment"
STAGE = "Feasibility & Assessment"
STEP = "Department assessment"

# (department_name, rasic_letter) for the rewritten stage-1 step.
NEW_RASIC = [
    ("R&D", "R"), ("Tool design", "R"), ("IE", "R"),
    ("Process Engineer", "R"), ("APQP", "R"), ("Quality", "R"),
    ("Logistics", "I"), ("Project Manager", "I"), ("Sales", "I"),
]


def _dept_id(bind, name):
    return bind.execute(
        sa.text("SELECT id FROM wf_departments WHERE name = :n"), {"n": name}
    ).scalar()


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Reactivate APQP.
    bind.execute(sa.text(
        "UPDATE wf_departments SET is_active = true WHERE name = 'APQP'"))

    # 2. Create Process Engineer if absent.
    if _dept_id(bind, "Process Engineer") is None:
        nxt = bind.execute(sa.text(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM wf_departments")).scalar()
        bind.execute(sa.text(
            "INSERT INTO wf_departments (name, flow_type, is_active, sort_order, created_at) "
            # CURRENT_TIMESTAMP, not now(): SQLite has no now().
            "VALUES ('Process Engineer', 'action', true, :so, CURRENT_TIMESTAMP)"), {"so": nxt})

    # 3. Rewrite the live stage-1 RASIC (create-if-absent seeding never updates
    #    an existing template). There may be more than one template named
    #    "ECM Assessment" (a seed duplicate) — rewrite every matching step.
    step_ids = [r[0] for r in bind.execute(sa.text("""
        SELECT st.id FROM wf_steps st
        JOIN wf_stages sg ON sg.id = st.stage_id
        JOIN wf_templates t ON t.id = sg.template_id
        WHERE t.name = :tpl AND sg.name = :stage AND st.step_name = :step
    """), {"tpl": TEMPLATE, "stage": STAGE, "step": STEP}).fetchall()]

    new_pairs = [(_dept_id(bind, n), l) for n, l in NEW_RASIC]
    for step_id in step_ids:
        bind.execute(sa.text(
            "DELETE FROM wf_step_rasic WHERE step_id = :s"), {"s": step_id})
        for did, letter in new_pairs:
            if did is not None:
                bind.execute(sa.text(
                    "INSERT INTO wf_step_rasic (step_id, department_id, rasic_letter) "
                    "VALUES (:s, :d, :l)"), {"s": step_id, "d": did, "l": letter})


def downgrade() -> None:
    # The prior stage-1 RASIC is not restored (it was the defect being fixed);
    # re-retiring APQP / dropping Process Engineer is likewise intentionally not
    # reversed to avoid orphaning any assessments created in the meantime.
    pass
