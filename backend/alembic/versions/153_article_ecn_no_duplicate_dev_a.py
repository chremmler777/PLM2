"""153: no second Development task on the Article check workflow's design
steps (audit 2026-10-29, P2-4).

Data ("ECN Implementation (Article)", every version present): on "Update 3D
data" and "Update drawings & documentation" Development is the designer (R),
so its A row was a second task for the same job (Christoph approved four
rows for two jobs). The A row goes where the same step already has a
Development R; the Design review (four-eyes, Quality A) checks the design.
The Tool template keeps Development A (there the Tool Engineer designs).

Running instances keep the tasks they already have; instances started from
now on get one task per step. Repeatable.

Downgrade: puts the Development A rows back.

Revision ID: 153
Revises: 152
"""
from alembic import op
import sqlalchemy as sa

revision = "153"
down_revision = "152"
branch_labels = None
depends_on = None

TEMPLATE = "ECN Implementation (Article)"
STEPS = ("Update 3D data", "Update drawings & documentation")


def _ids(bind):
    insp = sa.inspect(bind)
    if "wf_step_rasic" not in insp.get_table_names():
        return None, []
    dev = bind.execute(sa.text(
        "SELECT id FROM wf_departments WHERE name = 'Development'")).scalar()
    if dev is None:
        return None, []
    steps = bind.execute(sa.text(
        "SELECT s.id FROM wf_steps s "
        "JOIN wf_stages st ON st.id = s.stage_id "
        "JOIN wf_templates t ON t.id = st.template_id "
        "WHERE t.name = :t AND s.step_name IN :names"
    ).bindparams(sa.bindparam("names", expanding=True)),
        {"t": TEMPLATE, "names": list(STEPS)}).scalars().all()
    return dev, list(steps)


def upgrade() -> None:
    bind = op.get_bind()
    dev, steps = _ids(bind)
    for step_id in steps:
        has_r = bind.execute(sa.text(
            "SELECT 1 FROM wf_step_rasic WHERE step_id = :s AND department_id = :d "
            "AND rasic_letter = 'R'"), {"s": step_id, "d": dev}).scalar()
        if has_r:
            bind.execute(sa.text(
                "DELETE FROM wf_step_rasic WHERE step_id = :s AND department_id = :d "
                "AND rasic_letter = 'A'"), {"s": step_id, "d": dev})


def downgrade() -> None:
    bind = op.get_bind()
    dev, steps = _ids(bind)
    for step_id in steps:
        has_a = bind.execute(sa.text(
            "SELECT 1 FROM wf_step_rasic WHERE step_id = :s AND department_id = :d "
            "AND rasic_letter = 'A'"), {"s": step_id, "d": dev}).scalar()
        if not has_a:
            bind.execute(sa.text(
                "INSERT INTO wf_step_rasic (step_id, department_id, rasic_letter) "
                "VALUES (:s, :d, 'A')"), {"s": step_id, "d": dev})
