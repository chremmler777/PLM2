"""142: who set a computed check's limits, and Quality's confirm of them
(close-out A5-02, spec §4/§10, R4/R7: the department being judged does not
set its own pass criterion alone).

Schema
  validation_checks.limits_set_by        who entered the limits (the first
                                         measurement's measurer, or Quality
                                         correcting them)
  validation_checks.limits_confirmed_by  who confirmed them (Quality, never
                                         the setter)
  validation_checks.limits_confirmed_at  when

Data
  limits_set_by backfilled from the check's first measurement; nothing is
  confirmed, so an in-flight PASS counts once Quality confirms its limits
  (one click on the check); a FAIL counts at once as before.

Revision ID: 142
Revises: 141
"""
import sqlalchemy as sa
from alembic import op

revision = "142"
down_revision = "141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("validation_checks",
                  sa.Column("limits_set_by", sa.Integer(),
                            sa.ForeignKey("users.id"), nullable=True))
    op.add_column("validation_checks",
                  sa.Column("limits_confirmed_by", sa.Integer(),
                            sa.ForeignKey("users.id"), nullable=True))
    op.add_column("validation_checks",
                  sa.Column("limits_confirmed_at", sa.DateTime(), nullable=True))
    op.execute("""
        UPDATE validation_checks c SET limits_set_by = m.measured_by
        FROM (SELECT DISTINCT ON (check_id) check_id, measured_by
              FROM validation_measurements ORDER BY check_id, id) m
        WHERE m.check_id = c.id AND c.lower_limit IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column("validation_checks", "limits_confirmed_at")
    op.drop_column("validation_checks", "limits_confirmed_by")
    op.drop_column("validation_checks", "limits_set_by")
