"""039: change_concerns — parallel team flags feeding the scoping decision.

The scoping decision is one event, but the opinions feeding it arrive in
parallel and from different people. Before this, an objection first became
visible when somebody pressed reject in the meeting, and the record showed only
who pressed the button — not who actually objected, or why.

A concern is a flag with an author, a kind (reject_proposal | needs_info) and a
note. It is withdrawn by its author, or resolved by the meeting decision that
answers it. Open concerns block 'proceed'.

Revision ID: 039
Revises: 038
"""
from alembic import op
import sqlalchemy as sa

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "change_concerns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("change_id", sa.Integer(),
                  sa.ForeignKey("change_requests.id"), nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("raised_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("raised_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
        sa.Column("withdrawn_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_by_meeting_id", sa.Integer(),
                  sa.ForeignKey("change_meetings.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("change_concerns")
