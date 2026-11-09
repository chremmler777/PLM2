"""160: changeover offered to the customer (Christoph 2026-11-09).

"Not that complex. For now Sales just offers running change or customer
scraps; Logistics will have the task after quoting ... It's only to tie the
customer down on its decision."

On the change: the offered mode (running_change | customer_scrap), and
optional details: old parts left, changeover date, a note; plus who set it
and when. The offer states it. bank_build_* (Logistics' plan after
acceptance) stays as it is and may prefill from it.

Revision ID: 160
Revises: 158 (no 159 at the time of writing; re-chain if one lands)
"""
import sqlalchemy as sa
from alembic import op

revision = "160"
down_revision = "158"
branch_labels = None
depends_on = None

COLS = ("changeover_offer_mode", "old_stock_parts", "changeover_date",
        "changeover_offer_note", "changeover_offer_set_by",
        "changeover_offer_set_at")


def upgrade() -> None:
    op.add_column("change_requests", sa.Column("changeover_offer_mode", sa.String(20), nullable=True))
    op.add_column("change_requests", sa.Column("old_stock_parts", sa.Integer(), nullable=True))
    op.add_column("change_requests", sa.Column("changeover_date", sa.Date(), nullable=True))
    op.add_column("change_requests", sa.Column("changeover_offer_note", sa.Text(), nullable=True))
    op.add_column("change_requests", sa.Column(
        "changeover_offer_set_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("change_requests", sa.Column("changeover_offer_set_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for col in reversed(COLS):
        op.drop_column("change_requests", col)
