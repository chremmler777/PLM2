"""155: Project Management approves the industrialization once (audit
2026-10-29 P2-4 second half; Christoph 2026-11-02).

Data (both "ECN Implementation (Tool)" and "(Article)" templates, every
version present): Project Manager was A on all four Industrialization steps,
so the PM approved four rows for one stage. PM stays A on the last step
("Update master data & logistics") only; its A row on "Implement tool
change", "Adjust process / parameter sheets" and "Clarify inspection plan /
PPAP need" goes. The seed is wf_seed_service.INDUSTRIALIZATION_STEPS.

Running instances keep the tasks they already have; instances started from
now on get one PM approval. Repeatable (deletes only what is there).

Downgrade: puts the three PM A rows back.

Revision ID: 155
Revises: 154
"""
from alembic import op
import sqlalchemy as sa

revision = "155"
down_revision = "154"
branch_labels = None
depends_on = None

TEMPLATES = ("ECN Implementation (Tool)", "ECN Implementation (Article)")
DROPPED = ("Implement tool change", "Adjust process / parameter sheets",
           "Clarify inspection plan / PPAP need")


def _ids(bind):
    if "wf_step_rasic" not in sa.inspect(bind).get_table_names():
        return None, []
    pm = bind.execute(sa.text(
        "SELECT id FROM wf_departments WHERE name = 'Project Manager'")).scalar()
    if pm is None:
        return None, []
    steps = bind.execute(sa.text(
        "SELECT s.id FROM wf_steps s "
        "JOIN wf_stages st ON st.id = s.stage_id "
        "JOIN wf_templates t ON t.id = st.template_id "
        "WHERE t.name IN :t AND s.step_name IN :names"
    ).bindparams(sa.bindparam("t", expanding=True),
                 sa.bindparam("names", expanding=True)),
        {"t": list(TEMPLATES), "names": list(DROPPED)}).scalars().all()
    return pm, list(steps)


def upgrade() -> None:
    bind = op.get_bind()
    pm, steps = _ids(bind)
    for step_id in steps:
        bind.execute(sa.text(
            "DELETE FROM wf_step_rasic WHERE step_id = :s AND department_id = :d "
            "AND rasic_letter = 'A'"), {"s": step_id, "d": pm})


def downgrade() -> None:
    bind = op.get_bind()
    pm, steps = _ids(bind)
    for step_id in steps:
        has = bind.execute(sa.text(
            "SELECT 1 FROM wf_step_rasic WHERE step_id = :s AND department_id = :d "
            "AND rasic_letter = 'A'"), {"s": step_id, "d": pm}).scalar()
        if not has:
            bind.execute(sa.text(
                "INSERT INTO wf_step_rasic (step_id, department_id, rasic_letter) "
                "VALUES (:s, :d, 'A')"), {"s": step_id, "d": pm})
