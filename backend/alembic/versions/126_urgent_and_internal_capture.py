"""126: urgent and internal capture (ECR-solid spec §2) and the urgent
proceed question (§3).

Schema (change_requests)
  urgent_reason / urgent_evidence    an urgent change (priority 'critical'):
                                     the reason pick and its evidence; the
                                     need-by date is release_due_date
  problem_value / problem_unit       internal: "what is wrong today", a number
                                     with its unit
  target_value                       ... and the target (same unit)
  need_by_check                      urgent proceed: need-by realistic?
                                     yes | at_risk | no
  need_by_proposed                   'no': the proposed date
  need_by_checked_by / _at
  need_by_told_ref / _by / _at       Sales told the customer (mail or ref)

Data: none. In-flight changes keep their priority; an urgent one owes its
need-by, reason and evidence at the next kickoff (soft) or edit.

Repeatable: every column is added once.

Revision ID: 126
Revises: 125
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "126"
down_revision = "125"
branch_labels = None
depends_on = None

COLUMNS = (
    ("urgent_reason", lambda: sa.String(30), None),
    ("urgent_evidence", lambda: sa.String(255), None),
    ("problem_value", lambda: sa.Float(), None),
    ("problem_unit", lambda: sa.String(20), None),
    ("target_value", lambda: sa.Float(), None),
    ("need_by_check", lambda: sa.String(10), None),
    ("need_by_proposed", lambda: sa.DateTime(), None),
    ("need_by_checked_by", lambda: sa.Integer(), "users"),
    ("need_by_checked_at", lambda: sa.DateTime(), None),
    ("need_by_told_ref", lambda: sa.String(255), None),
    ("need_by_told_by", lambda: sa.Integer(), "users"),
    ("need_by_told_at", lambda: sa.DateTime(), None),
)


def _columns() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns("change_requests")}


def upgrade() -> None:
    have = _columns()
    for name, typ, fk in COLUMNS:
        if name in have:
            continue
        args = [sa.ForeignKey(f"{fk}.id")] if fk else []
        op.add_column("change_requests", sa.Column(name, typ(), *args, nullable=True))


def downgrade() -> None:
    have = _columns()
    for name, _, _ in reversed(COLUMNS):
        if name in have:
            op.drop_column("change_requests", name)
