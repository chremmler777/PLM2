"""141: the customer's go-ahead for a start at risk keeps its file id
(close-out A4-06, spec §7a "customer go-ahead evidence", R4/R17).

Schema
  change_requests.start_at_risk_attachment_id   the filed mail or file the
                                                go-ahead stands on (NULL: a
                                                reference, or an ask before
                                                this migration)

Data
  none: an ask before this keeps its text ("Mail: <filename>") only; a new
  ask with a file stores its id, and that file is frozen (409 on delete).

Revision ID: 141
Revises: 140
"""
import sqlalchemy as sa
from alembic import op

revision = "141"
down_revision = "140"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_requests",
                  sa.Column("start_at_risk_attachment_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("change_requests", "start_at_risk_attachment_id")
