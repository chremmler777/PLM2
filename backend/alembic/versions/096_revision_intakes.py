"""096: revision intake, every new customer index is captured and triaged
(spec 2026-09-25 §17 / §17a).

- revision_intakes: one row per new customer major that came in through a
  gated path (customer package, customer data, upload, promote). The
  revision stays pending (status in_review, not the part's active one)
  until Development decides the route: full_ecr | attach_ecr |
  engineering_review | administrative.
- change_review_answers: the light engineering review (origin
  "engineering_review"): one row per department asked, "no impact" or
  "impact" with a note.

Existing revisions are untouched: only indexes received after deploy create
intakes. Dialect-neutral, same file on Postgres and SQLite.

Revision ID: 096
Revises: 095
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "revision_intakes" not in tables:
        op.create_table(
            "revision_intakes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("revision_id", sa.Integer(), sa.ForeignKey("part_revisions.id"),
                      nullable=False),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("batch_id", sa.String(36), nullable=True),
            sa.Column("received_at", sa.Date(), nullable=True),
            sa.Column("received_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("revision_phase", sa.String(20), nullable=True),
            sa.Column("part_phase", sa.String(20), nullable=True),
            sa.Column("suggested_route", sa.String(30), nullable=True),
            sa.Column("route", sa.String(30), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"),
                      nullable=True),
            sa.Column("promoted_from_revision_id", sa.Integer(),
                      sa.ForeignKey("part_revisions.id"), nullable=True),
            sa.Column("activated_at", sa.DateTime(), nullable=True),
            sa.Column("activated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("escalated_at", sa.DateTime(), nullable=True),
            sa.Column("escalated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("superseded_by_id", sa.Integer(),
                      sa.ForeignKey("revision_intakes.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("revision_id", name="uq_revision_intake_revision"),
        )
        op.create_index("ix_revision_intakes_part_id", "revision_intakes", ["part_id"])
        op.create_index("ix_revision_intakes_project_id", "revision_intakes", ["project_id"])
        op.create_index("ix_revision_intakes_status", "revision_intakes", ["status"])
        op.create_index("ix_revision_intakes_change_id", "revision_intakes", ["change_id"])
        op.create_index("ix_revision_intakes_batch_id", "revision_intakes", ["batch_id"])

    if "change_review_answers" not in tables:
        op.create_table(
            "change_review_answers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"),
                      nullable=False),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                      nullable=False),
            sa.Column("answer", sa.String(20), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("answered_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("change_id", "department_id", name="uq_change_review_answer"),
        )
        op.create_index("ix_change_review_answers_change_id", "change_review_answers",
                        ["change_id"])


def downgrade() -> None:
    op.drop_index("ix_change_review_answers_change_id", table_name="change_review_answers")
    op.drop_table("change_review_answers")
    for ix in ("batch_id", "change_id", "status", "project_id", "part_id"):
        op.drop_index(f"ix_revision_intakes_{ix}", table_name="revision_intakes")
    op.drop_table("revision_intakes")
