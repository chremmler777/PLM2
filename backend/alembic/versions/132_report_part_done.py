"""132: "our part done" on a progress report (ECR-solid C23, spec §8-9).

Schema
  implementation_reports.part_done   the department's part of the
                                     implementation is done: its report
                                     cadence ends (a later report without it
                                     restarts the cadence)

Data: none; existing reports are not "done".

Repeatable: the column is added once.

Revision ID: 132
Revises: 131
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "132"
down_revision = "131"
branch_labels = None
depends_on = None


def _have() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns("implementation_reports")}


def upgrade() -> None:
    if "part_done" not in _have():
        op.add_column("implementation_reports", sa.Column(
            "part_done", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    if "part_done" in _have():
        op.drop_column("implementation_reports", "part_done")
