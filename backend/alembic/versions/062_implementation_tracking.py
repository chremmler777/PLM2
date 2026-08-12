"""062: stage 8 — what implementation actually costs, and what it is doing.

Implementation is the one stage where the system had nothing but a status. The
change sits in 'in_implementation' for weeks, departments burn hours on it,
and the only thing anybody could read out of the database was the date it
entered the stage. Three tables fix that, and each of them answers a different
question that gets asked in a real programme review:

  implementation_bookings   HOW MUCH did this cost us, really. One row per
                            chunk of time a department books against the
                            change. Deliberately hours-only and NOT priced
                            here: the rate that applies is the department's
                            rate at the plant (department_rate), and freezing
                            a euro amount into the booking would make the
                            actuals P&L at validation disagree with the
                            costing it is supposed to be compared against.
                            The booking is the fact; the money is derived.

  implementation_reports    WHAT IS HAPPENING. The rule book says every
                            implementing department reports at least twice a
                            week, and carries an at-risk flag when it will not
                            make the timeline. The flag is the point of the
                            table — a note nobody can filter on is a note
                            nobody reads. risk_note is nullable on purpose:
                            demanding a written justification before a
                            department may raise its hand is how at-risk flags
                            stop being raised. Recommended, never gated.

  implementation_escalations The answer to a flag. Sales owns the customer, so
                            Sales decides whether a flagged risk goes OUT
                            ('customer' — the delivery date moves and they
                            have to hear it from us) or stays IN ('internal' —
                            we re-plan around it). report_id points at the
                            flagged report it answers, and is nullable because
                            an escalation can also be raised off a
                            conversation rather than off a specific report.
                            resolved_at/resolution_note close the loop: an
                            escalation with no ending is indistinguishable
                            from one nobody looked at.

Who counts as an "implementing department" is derived, not stored: the
departments that put a costing position or a cost line on this change are the
ones that priced work, and the ones that priced work are the ones that do it.
A membership table here would be a second list to keep in sync with costing,
and it would be wrong the first time someone edited the costing.

No new status and no new transition gate. Stage 8 pressure comes from my-tasks
rows (progress_report, escalate_risk) computed off these tables, the same call
061 made for the scheduling block.

All three tables are new, so the foreign keys are real ones — the ORM-level-FK
workaround in 049/051/055/057/059/061 exists because SQLite cannot ADD COLUMN
with a constraint, which does not apply to CREATE TABLE.

Revision ID: 062
Revises: 061
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "implementation_bookings" not in tables:
        op.create_table(
            "implementation_bookings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False,
                      index=True),
            sa.Column("department_id", sa.Integer(),
                      sa.ForeignKey("wf_departments.id"), nullable=False,
                      index=True),
            # Strictly positive; enforced in the service so the message can
            # say why. A zero booking is not a fact about the work, and a
            # negative one is a correction that belongs in DELETE + re-book.
            sa.Column("hours", sa.Numeric(8, 2), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("booked_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=False),
            sa.Column("booked_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
        )

    if "implementation_reports" not in tables:
        op.create_table(
            "implementation_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False,
                      index=True),
            sa.Column("department_id", sa.Integer(),
                      sa.ForeignKey("wf_departments.id"), nullable=False,
                      index=True),
            # A report with no text is a checkbox, and a checkbox tells the
            # next review nothing. Required.
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("at_risk", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column("risk_note", sa.Text(), nullable=True),
            sa.Column("reported_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=False),
            sa.Column("reported_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
        )

    if "implementation_escalations" not in tables:
        op.create_table(
            "implementation_escalations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False,
                      index=True),
            # The flagged report this answers. Nullable: Sales can also
            # escalate off a phone call, and forcing a synthetic report first
            # would make the report table lie about who observed what.
            sa.Column("report_id", sa.Integer(),
                      sa.ForeignKey("implementation_reports.id"),
                      nullable=True, index=True),
            # customer | internal — the vocabulary lives in
            # app/models/change_impl.py (ESCALATION_DIRECTIONS) where the API
            # validates against it; a CHECK here would be a copy to drift.
            sa.Column("direction", sa.String(10), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=True),
            sa.Column("resolution_note", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    pass  # forward-only
