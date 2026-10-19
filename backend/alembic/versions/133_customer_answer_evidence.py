"""133: the customer's answer with its evidence (ECR-solid §7, C4, C12).

Schema
  change_offers.accept_evidence     what the customer's yes rests on (JSON):
                                    {kind: file|mail|po, ref, attachment_id,
                                    po_match: yes|no, differs, total, indexes}
  change_offers.answered_at/by      when and who recorded the answer on
                                    this version (accepted or declined)
  change_requests.customer_next_contact
                                    "Still talking": the next contact date
                                    (the Sales task is due then)

Data: none. Answers recorded before carry no evidence (shown as "before
evidence was required"); in-flight quoted changes answer with the new form.

Repeatable: each column is added once.

Revision ID: 133
Revises: 132
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "133"
down_revision = "132"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols("change_offers")
    if "accept_evidence" not in have:
        op.add_column("change_offers", sa.Column("accept_evidence", sa.JSON(), nullable=True))
    if "answered_at" not in have:
        op.add_column("change_offers", sa.Column("answered_at", sa.DateTime(), nullable=True))
    if "answered_by" not in have:
        op.add_column("change_offers", sa.Column(
            "answered_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    if "customer_next_contact" not in _cols("change_requests"):
        op.add_column("change_requests", sa.Column(
            "customer_next_contact", sa.Date(), nullable=True))


def downgrade() -> None:
    have = _cols("change_offers")
    for col in ("answered_by", "answered_at", "accept_evidence"):
        if col in have:
            op.drop_column("change_offers", col)
    if "customer_next_contact" in _cols("change_requests"):
        op.drop_column("change_requests", "customer_next_contact")
