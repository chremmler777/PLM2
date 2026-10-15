"""122: ppap_decision and the customer flip (ECR-solid spec §0, §3, HARD #7).

Schema (change_requests)
  ppap_decision            'no' | 'yes' (Quality, internal changes, before proceed)
  ppap_basis / ppap_ref    a 'no': control_plan | process_sheet | customer_spec + reference
  ppap_part_ids            a 'yes': the parts whose parameters / tool / material /
                           cycle time changed
  ppap_decided_by / _at
  customer_flip_at / customer_flip_reason   an internal change became a customer one
  flip_answer              the Sales owner's answer: notification | offer
  flip_ref / flip_answered_by / flip_answered_at

Data: none. In-flight internal changes in scoping get Quality's ppap card;
nothing they already passed is re-gated.

Repeatable: every column is added once.

Revision ID: 122
Revises: 121
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "122"
down_revision = "121"
branch_labels = None
depends_on = None

COLUMNS = (
    ("ppap_decision", lambda: sa.String(5), None),
    ("ppap_basis", lambda: sa.String(20), None),
    ("ppap_ref", lambda: sa.String(255), None),
    ("ppap_part_ids", lambda: sa.JSON(), None),
    ("ppap_decided_by", lambda: sa.Integer(), "users"),
    ("ppap_decided_at", lambda: sa.DateTime(), None),
    ("customer_flip_at", lambda: sa.DateTime(), None),
    ("customer_flip_reason", lambda: sa.String(255), None),
    ("flip_answer", lambda: sa.String(15), None),
    ("flip_ref", lambda: sa.String(255), None),
    ("flip_answered_by", lambda: sa.Integer(), "users"),
    ("flip_answered_at", lambda: sa.DateTime(), None),
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
