"""143: stamp the go-live of the ECR-solid task clock (close-out A6-01, R8,
R21, R31).

Data
  org_settings 'cm_task_clock_from' = this migration's run time (ISO), one
  row per organization, only where none is set. A computed My Tasks row never
  counts from before it (app/services/due_rules.py clock_floor), so changes
  in flight at go-live are not all Late, escalated to leads and listed in
  the digests on the first sweep. CM_TASK_CLOCK_FROM in the environment
  still wins; an admin may edit or delete the row.

Repeatable: an existing row is kept. Downgrade removes the key.

Revision ID: 143
Revises: 142
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "143"
down_revision = "142"
branch_labels = None
depends_on = None

KEY = "cm_task_clock_from"


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.utcnow().replace(microsecond=0)
    # row by row with plain binds: PostgreSQL cannot type a bind used in a
    # SELECT list and a WHERE at once, SQLite would mangle a CAST
    have = {r[0] for r in bind.execute(sa.text(
        "SELECT organization_id FROM org_settings WHERE key = :k"), {"k": KEY})}
    for (org_id,) in bind.execute(sa.text("SELECT id FROM organizations")).all():
        if org_id in have:
            continue
        bind.execute(sa.text(
            "INSERT INTO org_settings (organization_id, key, value, updated_at) "
            "VALUES (:org, :k, :v, :at)"),
            {"org": org_id, "k": KEY, "v": now.isoformat(), "at": now})


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM org_settings WHERE key = :key"),
                          {"key": KEY})
