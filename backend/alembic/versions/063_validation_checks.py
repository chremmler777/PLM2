"""063: stage 9 — validation as a set of checks somebody signs, not a status.

Until now 'in_validation' was a waiting room with a door at the end of it. The
rule book says something much more specific: every implementing department
fulfils ITS OWN checks on the change — the tool was sampled, the part was
measured, the cycle time was measured AND WRITTEN DOWN — and two departments
carry an extra one. The Tool Engineer weighs the sampled part against the
weight the quote was built on, and Development confirms the revision levels
were raised the way the customer's statement said they would be. Only when the
checks are in does the change get released; when one fails it goes back to
implementation with PM and Sales re-planning the timing and the commercial
terms.

  validation_checks   One row per (change, department, check). The row IS the
                      signature: who ticked it, when, and — for the two checks
                      that are a MEASUREMENT rather than a yes — the number
                      they measured. `value` is deliberately one untyped
                      Numeric column with the unit implied by check_key
                      (cycle_time in seconds, weight in grams) rather than two
                      typed columns that are NULL for every other check: the
                      catalog in app/services/validation_checklist.py says
                      which key expects a value and in what unit, and that
                      catalog is the only place the vocabulary lives.

                      The unique constraint is what makes the rows idempotent.
                      They are created lazily from the catalog the first time
                      anyone reads or writes the validation state, so a change
                      that never entered stage 9 carries no rows at all — and
                      that absence is meaningful: the released guard passes
                      vacuously for changes with zero rows, which is what keeps
                      every change created before this migration releasable.

                      status is a String, not an enum: the vocabulary
                      (open|passed|failed) lives in app/models/change_validation
                      .py where the API validates against it, and a CHECK
                      constraint here would be a second copy to drift.

  change_requests.weight_delta_ack_*   The commercial half of the weight
                      check. Validating the weight is a technical act; the
                      DELTA against the estimate is money, and the quote has
                      to be updated with it. Sales gets a my-tasks row for as
                      long as the delta is nonzero and unacknowledged, and
                      this stamp is the acknowledgement — "the quote was
                      updated, or we decided to eat it". Not a boolean: who
                      decided and when is the whole value of the record.

Which departments must check is DERIVED, exactly as stage 8 derives it
(ImplementationService.implementing_department_ids): the departments that
priced work on the change. A membership table would be a second list to
disagree with the costing.

The three change_requests columns are ORM-level FK only — SQLite cannot ADD
COLUMN with a constraint, the same call 049/051/055/057/059/061 made. The new
table is a CREATE TABLE, so its foreign keys are real.

Revision ID: 063
Revises: 062
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


_CHANGE_COLUMNS = (
    ("weight_delta_ack_at", lambda: sa.Column(
        "weight_delta_ack_at", sa.DateTime(), nullable=True)),
    ("weight_delta_ack_by", lambda: sa.Column(
        "weight_delta_ack_by", sa.Integer(), nullable=True)),
    ("weight_delta_ack_note", lambda: sa.Column(
        "weight_delta_ack_note", sa.Text(), nullable=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "validation_checks" not in tables:
        op.create_table(
            "validation_checks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False,
                      index=True),
            sa.Column("department_id", sa.Integer(),
                      sa.ForeignKey("wf_departments.id"), nullable=False,
                      index=True),
            # The catalog key: sampled | measured | cycle_time | weight |
            # revision_bump. 40 chars leaves room for keys the rule book has
            # not invented yet without a migration to widen.
            sa.Column("check_key", sa.String(40), nullable=False),
            # open | passed | failed (VALIDATION_CHECK_STATUSES).
            sa.Column("status", sa.String(10), nullable=False,
                      server_default="open"),
            # The measurement, when the check is one: seconds for cycle_time,
            # grams for weight. Three decimals because a cycle time argument
            # is about tenths of a second.
            sa.Column("value", sa.Numeric(12, 3), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            # Nullable because a freshly seeded row is nobody's statement yet.
            sa.Column("checked_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("change_id", "department_id", "check_key",
                                name="uq_validation_check"),
        )

    if "change_requests" in tables:
        cols = {c["name"] for c in insp.get_columns("change_requests")}
        for name, make in _CHANGE_COLUMNS:
            if name not in cols:
                op.add_column("change_requests", make())


def downgrade() -> None:
    pass  # forward-only
