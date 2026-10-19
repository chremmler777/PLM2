"""131: who owns the tool change and the trial in the check workflows
(ECR-solid C21, spec §8-9 "Reseed").

Data (both "ECN Implementation (Tool)" and "(Article)" templates, every
version present): the industrialization and ready-to-go steps get the owners
of app/services/wf_seed_service.py (INDUSTRIALIZATION_STEPS,
READY_TO_GO_STEPS):
  Implement tool change           Tool Engineer R, Project Manager A,
                                  Toolshop S, Process Engineer C
  Adjust process / parameter      Process Engineer R, Project Manager A,
  sheets (was "routing sheets")   Manufacturing Engineer C
  Clarify inspection plan / PPAP  unchanged
  Update master data & logistics  Scheduling R, Project Manager A
  Sampling / trial                Tool Engineer R, Quality A,
                                  Process Engineer S
  Final release                   Project Manager R, Quality A, Sales I
The retired Production, Production control, Purchasing and Logistics rows go.
A department missing from the database is skipped (never created here).

Running instances keep the tasks they already have; the new owners apply to
instances started from now on (in plm_ecr_solid no change is past approved).

Downgrade: none (the old owners were the audit finding).

Revision ID: 131
Revises: 130
"""
from alembic import op
import sqlalchemy as sa

revision = "131"
down_revision = "130"
branch_labels = None
depends_on = None

TEMPLATES = ("ECN Implementation (Tool)", "ECN Implementation (Article)")
RENAME = {"Adjust process / routing sheets": "Adjust process / parameter sheets"}
OWNERS = {
    "Implement tool change": [("Tool Engineer", "R"), ("Project Manager", "A"),
                              ("Toolshop", "S"), ("Process Engineer", "C")],
    "Adjust process / parameter sheets": [("Process Engineer", "R"),
                                          ("Project Manager", "A"),
                                          ("Manufacturing Engineer", "C")],
    "Update master data & logistics": [("Scheduling", "R"), ("Project Manager", "A")],
    "Sampling / trial": [("Tool Engineer", "R"), ("Quality", "A"),
                         ("Process Engineer", "S")],
    "Final release": [("Project Manager", "R"), ("Quality", "A"), ("Sales", "I")],
}


def upgrade() -> None:
    bind = op.get_bind()
    depts = {n: i for i, n in bind.execute(sa.text(
        "SELECT id, name FROM wf_departments")).all()}
    steps = bind.execute(sa.text(
        "SELECT st.id, st.step_name FROM wf_steps st "
        "JOIN wf_stages sg ON sg.id = st.stage_id "
        "JOIN wf_templates t ON t.id = sg.template_id "
        "WHERE t.name IN :names").bindparams(
            sa.bindparam("names", expanding=True)), {"names": list(TEMPLATES)}).all()
    for step_id, name in steps:
        new_name = RENAME.get(name, name)
        if new_name != name:
            bind.execute(sa.text("UPDATE wf_steps SET step_name = :n WHERE id = :i"),
                         {"n": new_name, "i": step_id})
        owners = OWNERS.get(new_name)
        if owners is None:
            continue
        bind.execute(sa.text("DELETE FROM wf_step_rasic WHERE step_id = :i"),
                     {"i": step_id})
        for dept, letter in owners:
            if dept in depts:
                bind.execute(sa.text(
                    "INSERT INTO wf_step_rasic (step_id, department_id, rasic_letter) "
                    "VALUES (:s, :d, :l)"), {"s": step_id, "d": depts[dept], "l": letter})


def downgrade() -> None:
    pass
