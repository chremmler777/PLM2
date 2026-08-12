"""061: the scheduling block — running change vs planned scrap, then published.

Acceptance is not a plan. Once the customer says yes ('approved'), Scheduling
has to say HOW the changeover happens on the real line, and there are only two
answers: the new state runs in as a **running change** (the old stock is
consumed, no bank is thrown away), or the bank on hand is **planned scrap**.
That second answer costs money, and the money is the customer's — so a planned
scrap is only a plan once an additional SCRAP QUOTE price exists behind it.
That is the whole reason scrap_quote_price sits next to the mode instead of in
the costing tables: it is not a cost line of the change, it is the condition
that makes one of the two modes sayable at all.

bank_build_note is the plan itself in the only form this system can carry
tonight: a summary or a reference to the schedule that was built elsewhere.
Deliberately Text and not a child table — the timeline that leads everything
downstream (samplings, blocked machines, stage 8's progress reports) is its own
build, and a half-modelled version of it here would be something to migrate
away from rather than onto.

Publication is a second, separately-stamped act by SALES, not a flag Scheduling
sets: the plan becomes a commitment when the customer has been told it, and who
told them and when is exactly what gets asked about later. Republishing
refreshes the stamp — the customer got a newer plan — and the changelog keeps
every round.

No new status and no new transition gate: 'approved' -> 'in_implementation'
stays open. The scheduling block makes itself visible through my-tasks rows and
the wait states derived from these columns, which is what a stage that is real
process but not yet a hard rule should do.

FKs are ORM-level only (SQLite cannot ADD COLUMN with a foreign key) — same
call as 049/051/055/057/059.

Revision ID: 061
Revises: 060
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


_COLUMNS = (
    # running_change | planned_scrap — the vocabulary lives in
    # app/models/change.py (BANK_BUILD_MODES), where the API validates against
    # it; a CHECK constraint here would be a second copy of it to drift.
    ("bank_build_mode", lambda: sa.Column(
        "bank_build_mode", sa.String(20), nullable=True)),
    ("bank_build_note", lambda: sa.Column(
        "bank_build_note", sa.Text(), nullable=True)),
    # The additional quote the customer is charged for scrapping the bank.
    # NULL on a running change, and nulled again when the mode flips back.
    ("scrap_quote_price", lambda: sa.Column(
        "scrap_quote_price", sa.Numeric(12, 2), nullable=True)),
    ("bank_build_set_by", lambda: sa.Column(
        "bank_build_set_by", sa.Integer(), nullable=True)),
    ("bank_build_set_at", lambda: sa.Column(
        "bank_build_set_at", sa.DateTime(), nullable=True)),
    ("plan_published_by", lambda: sa.Column(
        "plan_published_by", sa.Integer(), nullable=True)),
    ("plan_published_at", lambda: sa.Column(
        "plan_published_at", sa.DateTime(), nullable=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_requests" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("change_requests")}
    for name, make in _COLUMNS:
        if name not in cols:
            op.add_column("change_requests", make())


def downgrade() -> None:
    pass  # forward-only
