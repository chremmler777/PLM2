"""037: rejection memo + reopen path on change_requests.

Rejecting a change was a one-click, unexplained, irreversible act: no reason was
captured and `rejected` was a dead-end state. Both are wrong for an audited
process — a rejection is a decision someone answers for later, and a change
rejected in error had no way back short of raising a new one.

Adds rejected_at / rejected_by / rejection_reason. The reopen path itself is a
transition-map change (rejected -> scoping) and needs no schema.

Revision ID: 037
Revises: 036
"""
from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_requests", sa.Column("rejected_at", sa.DateTime(), nullable=True))
    op.add_column("change_requests", sa.Column("rejected_by", sa.Integer(), nullable=True))
    op.add_column("change_requests", sa.Column("rejection_reason", sa.Text(), nullable=True))
    # Existing rejected rows predate the memo; there is nothing truthful to
    # backfill, and inventing a reason would be worse than leaving it null.


def downgrade() -> None:
    op.drop_column("change_requests", "rejection_reason")
    op.drop_column("change_requests", "rejected_by")
    op.drop_column("change_requests", "rejected_at")
