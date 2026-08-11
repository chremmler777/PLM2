"""038: change_meetings.decision_reason.

A scoping meeting that rejects a change, or sends it back for more information,
owes the originator an answer. Both decisions were previously a bare button
press with nothing recorded beyond the verb.

'reject' feeds the change's rejection_reason (037); 'needs_info' states what is
missing, which is what Sales then has to go and get.

Revision ID: 038
Revises: 037
"""
from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_meetings", sa.Column("decision_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("change_meetings", "decision_reason")
