"""139: the Fix task and the parallel concession of a failed validation
check (ECR-solid §10, lane L7, switch RELEASE_V2).

Schema (change_validation_issues)
  fix_owner_kind              process_parameters | tool_at_supplier | other
  fix_department_id           the department that fixes (Quality's pick)
  retest_due                  the retest date Quality set
  fix_set_by / fix_set_at     who picked, when
  concession_requested_at/by  Quality asked for a concession
  concession_quantity         accepted for this many parts (or until a date:
                              concession_until, existing)
  concession_not_for_shipment internal change: parts not for shipment
  concession_reminded_at      the reminder 10 wd before concession_until

Data: none. An issue raised before this migration keeps its 8D route; it
gets a Fix task only while its check is failed and no fix owner is set.

Repeatable: every column is added once.

Revision ID: 139
Revises: 138
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "139"
down_revision = "138"
branch_labels = None
depends_on = None

TABLE = "change_validation_issues"
COLUMNS = (
    ("fix_owner_kind", lambda: sa.String(20)),
    ("fix_department_id", lambda: sa.Integer()),
    ("retest_due", lambda: sa.Date()),
    ("fix_set_by", lambda: sa.Integer()),
    ("fix_set_at", lambda: sa.DateTime()),
    ("concession_requested_at", lambda: sa.DateTime()),
    ("concession_requested_by", lambda: sa.Integer()),
    ("concession_quantity", lambda: sa.Integer()),
    ("concession_not_for_shipment", lambda: sa.Boolean()),
    ("concession_reminded_at", lambda: sa.DateTime()),
)
FKS = {"fix_department_id": "wf_departments.id", "fix_set_by": "users.id",
       "concession_requested_by": "users.id"}


def _have() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    have = _have()
    for name, kind in COLUMNS:
        if name not in have:
            args = [sa.ForeignKey(FKS[name])] if name in FKS else []
            op.add_column(TABLE, sa.Column(name, kind(), *args, nullable=True))


def downgrade() -> None:
    have = _have()
    with op.batch_alter_table(TABLE) as batch:
        for name, _ in reversed(COLUMNS):
            if name in have:
                batch.drop_column(name)
