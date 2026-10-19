"""125: revision intake triage and its follow-ups (ECR-solid spec §1, C9, C11).

Schema
  revision_intakes.what_changed         areas: geometry, tolerance, material,
                                        colour_grain, other | ['none']
  revision_intakes.what_changed_ref     compare report, drawing change block or file
  revision_intakes.no_change_reason     'no visible change' needs a reason
  revision_intakes.live_change_reason   full_ecr although a live change carries the part
  revision_intakes.customer_driven      attach to an internal change: customer-driven?
  revision_intakes.replaced_revision    the index it replaced inside the change (C, for C -> D)
  revision_intakes.scope_answer / _note / _by / _at
                                        the lead's "Index D adds parts or departments?"
  revision_intakes.deadline_needed      an open quote: Sales owes "D replaces C; deadline holds?"
  revision_intakes.deadline_answer      holds | new_date | not_asked
  revision_intakes.deadline_ref / deadline_confirm_by / deadline_by / deadline_at
  change_requests.related_change_id     full_ecr beside a live change, both ways
  change_rechecks                       one per routed department that had submitted:
                                        per area 'no effect' (ref) or 'effect' (what + evidence)

Data: none. In-flight changes have no intake follow-ups; the new columns are
NULL and nothing waits on them.

Repeatable: every column and the table are added once.

Revision ID: 125
Revises: 124
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "125"
down_revision = "124"
branch_labels = None
depends_on = None

INTAKE_COLUMNS = (
    ("what_changed", lambda: sa.JSON(), None),
    ("what_changed_ref", lambda: sa.String(255), None),
    ("no_change_reason", lambda: sa.String(255), None),
    ("live_change_reason", lambda: sa.String(30), None),
    ("customer_driven", lambda: sa.Boolean(), None),
    ("replaced_revision", lambda: sa.String(20), None),
    ("scope_answer", lambda: sa.String(5), None),
    ("scope_note", lambda: sa.String(500), None),
    ("scope_by", lambda: sa.Integer(), "users"),
    ("scope_at", lambda: sa.DateTime(), None),
    ("deadline_needed", lambda: sa.Boolean(), None),
    ("deadline_answer", lambda: sa.String(10), None),
    ("deadline_ref", lambda: sa.String(255), None),
    ("deadline_confirm_by", lambda: sa.DateTime(), None),
    ("deadline_by", lambda: sa.Integer(), "users"),
    ("deadline_at", lambda: sa.DateTime(), None),
)


def _inspector():
    return inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in _inspector().get_columns(table)}


def upgrade() -> None:
    have = _columns("revision_intakes")
    for name, typ, fk in INTAKE_COLUMNS:
        if name in have:
            continue
        args = [sa.ForeignKey(f"{fk}.id")] if fk else []
        op.add_column("revision_intakes", sa.Column(name, typ(), *args, nullable=True))
    if "related_change_id" not in _columns("change_requests"):
        op.add_column("change_requests", sa.Column(
            "related_change_id", sa.Integer(), sa.ForeignKey("change_requests.id"),
            nullable=True))
    if "change_rechecks" not in _inspector().get_table_names():
        op.create_table(
            "change_rechecks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"),
                      nullable=False, index=True),
            sa.Column("intake_id", sa.Integer(), sa.ForeignKey("revision_intakes.id"),
                      nullable=False, index=True),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                      nullable=False),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=True),
            sa.Column("from_revision", sa.String(20), nullable=True),
            sa.Column("to_revision", sa.String(20), nullable=True),
            sa.Column("areas", sa.JSON(), nullable=True),
            sa.Column("answers", sa.JSON(), nullable=True),
            sa.Column("something_else", sa.Text(), nullable=True),
            sa.Column("effect", sa.Boolean(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="open"),
            sa.Column("answered_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("intake_id", "department_id",
                                name="uq_change_recheck_intake_department"),
        )


def downgrade() -> None:
    if "change_rechecks" in _inspector().get_table_names():
        op.drop_table("change_rechecks")
    if "related_change_id" in _columns("change_requests"):
        op.drop_column("change_requests", "related_change_id")
    have = _columns("revision_intakes")
    for name, _, _ in reversed(INTAKE_COLUMNS):
        if name in have:
            op.drop_column("revision_intakes", name)
