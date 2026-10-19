"""136: start at risk (ECR-solid §7a, P8 decided: urgent only, switch ON).

Schema (change_requests)
  start_at_risk_evidence        the customer's go-ahead (filed mail or ref)
  start_at_risk_requested_by/at who asked (Sales or the run team), when
  start_at_risk_quality_note    Quality's one line of quality risks
  start_at_risk_quality_by/at
  start_at_risk_approved_by/at  the Project Management member (second: an
                                admin) who approved it; set = the change was
                                approved without the customer's acceptance

Data: none (no change started at risk before).

Repeatable: each column is added once.

Revision ID: 136
Revises: 135
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "136"
down_revision = "135"
branch_labels = None
depends_on = None

_COLS = (
    ("start_at_risk_evidence", lambda: sa.String(255), None),
    ("start_at_risk_requested_by", lambda: sa.Integer(), "users.id"),
    ("start_at_risk_requested_at", lambda: sa.DateTime(), None),
    ("start_at_risk_quality_note", lambda: sa.Text(), None),
    ("start_at_risk_quality_by", lambda: sa.Integer(), "users.id"),
    ("start_at_risk_quality_at", lambda: sa.DateTime(), None),
    ("start_at_risk_approved_by", lambda: sa.Integer(), "users.id"),
    ("start_at_risk_approved_at", lambda: sa.DateTime(), None),
)


def _have() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns("change_requests")}


def upgrade() -> None:
    have = _have()
    for name, typ, fk in _COLS:
        if name not in have:
            args = [sa.ForeignKey(fk)] if fk else []
            op.add_column("change_requests", sa.Column(name, typ(), *args, nullable=True))


def downgrade() -> None:
    have = _have()
    for name, _, _ in reversed(_COLS):
        if name in have:
            op.drop_column("change_requests", name)
