"""060: the negotiation loop at 'quoted' — rounds with the customer.

A quote going out is not the end of the commercial conversation. The customer
calls back, names a different number, asks for a different date, and the two
sides go around several times before anybody says yes. Until now only the
outcome survived (quoted_price, then the acceptance stamp), so a three-month
negotiation left no trace of WHY the number moved — the one thing anybody asks
about afterwards.

One row per round: how it happened (channel: meeting | call | email — a
customer negotiation happens by phone, which the scoping-meeting vocabulary
does not have), what came out of it (note, required — a round with no result is
not a record of anything), and the customer's counter when they stated one
(counter_price, nullable: plenty of rounds move only the date).

is_final marks THE result — the round the negotiation ended on. Exactly one per
change, enforced at the service boundary (a new final demotes its siblings)
rather than by a partial unique index, so the rule reads in the same place as
the rest of the vocabulary and cannot be half-enforced across two engines.

The final round's counter_price is read THROUGH onto the change as
negotiated_final_price — deliberately not a new column on change_requests:
quoted_price is what we offered and must stay what we offered, and what the
customer agreed to is a fact about the round that closed it.

Sales' go-ahead itself gets no new storage: acceptance (with its mandatory
release deadline) is existing mechanics and stays the only way a quoted change
moves on. This table is what that decision is taken on.

Additive only, and forward-only like every migration in this tree.

Revision ID: 060
Revises: 059
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_negotiations" in set(insp.get_table_names()):
        return
    op.create_table(
        "change_negotiations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("change_id", sa.Integer(),
                  sa.ForeignKey("change_requests.id"), nullable=False,
                  index=True),
        # meeting | call | email — the vocabulary lives in app/models/change.py
        # (NEGOTIATION_CHANNELS), where the API validates against it; a CHECK
        # constraint here would be a second copy of it to drift.
        sa.Column("channel", sa.String(15), nullable=False,
                  server_default="call"),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("counter_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_final", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.current_timestamp()),
    )


def downgrade() -> None:
    pass  # forward-only
