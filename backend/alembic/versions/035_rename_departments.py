"""035: rename departments to their business names.

  Tool design -> Tooling Engineer
  IE          -> Manufacturing Engineer

The retired, orphaned seed shells "Tool Engineer" and "Manufacturing Engineer"
(merged away in 032, 0 references) are deleted first — the latter frees the
"Manufacturing Engineer" name for the rename.

Revision ID: 035
Revises: 034
"""
from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None

RENAMES = [("Tool design", "Tooling Engineer"), ("IE", "Manufacturing Engineer")]
DROP_SHELLS = ["Tool Engineer", "Manufacturing Engineer"]


def upgrade() -> None:
    bind = op.get_bind()
    # Drop the orphaned retired shells (0 refs after 032) so the names are free.
    for name in DROP_SHELLS:
        bind.execute(sa.text(
            "DELETE FROM wf_departments WHERE name = :n AND is_active = false"),
            {"n": name})
    for old, new in RENAMES:
        bind.execute(sa.text(
            "UPDATE wf_departments SET name = :new WHERE name = :old"),
            {"new": new, "old": old})


def downgrade() -> None:
    for old, new in RENAMES:
        bind = op.get_bind()
        bind.execute(sa.text(
            "UPDATE wf_departments SET name = :old WHERE name = :new"),
            {"old": old, "new": new})
