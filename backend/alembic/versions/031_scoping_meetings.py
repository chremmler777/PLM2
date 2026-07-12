"""031: Scoping stage groundwork — meeting records, effort tracking, internal
cost approval, gate-seeding change.

- change_meetings table (pre-determination meeting module)
- change_assessments.effort_hours (time spent on the feasibility check)
- change_requests internal_approved_* columns (internal costing branch)
- removes undecided feasibility/budget gate rows on not-yet-started
  (captured) changes: those decisions are superseded by the scoping meeting
  and the costing path split. Decided rows and in-flight changes keep their
  gates so history stays truthful.

Revision ID: 031
Revises: 030
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if "change_meetings" not in insp.get_table_names():
        op.create_table(
            "change_meetings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False, index=True),
            sa.Column("meeting_date", sa.DateTime(), nullable=False),
            sa.Column("participants", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("decision", sa.String(20), nullable=True),
            sa.Column("selected_department_ids", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
        )

    cols = {c["name"] for c in insp.get_columns("change_assessments")}
    if "effort_hours" not in cols:
        op.add_column("change_assessments",
                      sa.Column("effort_hours", sa.Float(), nullable=True))

    cr_cols = {c["name"] for c in insp.get_columns("change_requests")}
    if "internal_approved_by" not in cr_cols:
        op.add_column("change_requests",
                      sa.Column("internal_approved_by", sa.Integer(), nullable=True))
    if "internal_approved_at" not in cr_cols:
        op.add_column("change_requests",
                      sa.Column("internal_approved_at", sa.DateTime(), nullable=True))
    if "internal_approved_amount" not in cr_cols:
        op.add_column("change_requests",
                      sa.Column("internal_approved_amount", sa.Float(), nullable=True))
    if "internal_approval_note" not in cr_cols:
        op.add_column("change_requests",
                      sa.Column("internal_approval_note", sa.Text(), nullable=True))

    op.execute(sa.text(
        "DELETE FROM change_gate WHERE decision = 'na' "
        "AND gate_key IN ('feasibility', 'budget') "
        "AND change_id IN (SELECT id FROM change_requests WHERE status = 'captured')"))


def downgrade() -> None:
    pass  # forward-only, consistent with 023-030
