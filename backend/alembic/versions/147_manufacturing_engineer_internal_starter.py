"""147: Manufacturing Engineer starts internal changes (D1, Christoph
2026-10-19).

P3 flagged Development, Process Engineer and Tool Engineer
(wf_departments.can_start_internal_change, migration 119). Manufacturing
Engineer (Russ, Cory: P2) joins them: its member may start an INTERNAL change
and, as for the others, the raiser leads it and its department is auto-R at
scoping. A customer change stays Sales' and Project Management's.

Data
  wf_departments.can_start_internal_change = true for "Manufacturing
  Engineer" (if the department exists). Repeatable; changes already open are
  untouched (their lead stays who it is).

Downgrade clears the flag again.

Revision ID: 147
Revises: 146
"""
import sqlalchemy as sa
from alembic import op

revision = "147"
down_revision = "146"
branch_labels = None
depends_on = None

DEPARTMENT = "Manufacturing Engineer"


def flag_internal_starters(bind, value: bool = True) -> None:
    bind.execute(sa.text(
        "UPDATE wf_departments SET can_start_internal_change = :v WHERE name = :n"),
        {"v": value, "n": DEPARTMENT})


def upgrade() -> None:
    flag_internal_starters(op.get_bind())


def downgrade() -> None:
    flag_internal_starters(op.get_bind(), False)
