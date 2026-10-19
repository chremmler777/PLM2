"""121: a concession records whether its yes was Quality's (ECR-solid C7, L2).

Schema
  change_validation_issues.customer_decided_as_quality
      True when the customer decision was recorded by a Quality member
      (acts-as aware: an admin acting as Quality counts, the same rule as a
      Quality override), False when somebody else recorded it. HARD #3 at
      release counts only a concession whose yes was Quality's.

Data
  rows with a recorded decision are backfilled from the decider's real
  Quality membership (the rule release used until now), so no in-flight
  change gains or loses a release by this migration.

Repeatable: the column is added once; the backfill only fills NULLs.

Revision ID: 121
Revises: 120
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "121"
down_revision = "120"
branch_labels = None
depends_on = None

TABLE = "change_validation_issues"
COLUMN = "customer_decided_as_quality"


def _has_table(table: str) -> bool:
    return table in inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_table(TABLE):
        return
    if COLUMN not in _columns(TABLE):
        with op.batch_alter_table(TABLE) as batch:
            batch.add_column(sa.Column(COLUMN, sa.Boolean(), nullable=True))
    op.execute(sa.text(f"""
        UPDATE {TABLE} SET {COLUMN} = EXISTS (
            SELECT 1 FROM user_departments ud
            JOIN wf_departments d ON d.id = ud.department_id
            WHERE ud.user_id = {TABLE}.customer_decided_by
              AND d.name = 'Quality' AND d.is_active)
        WHERE customer_decided_by IS NOT NULL AND {COLUMN} IS NULL
    """))


def downgrade() -> None:
    if not _has_table(TABLE) or COLUMN not in _columns(TABLE):
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN)
