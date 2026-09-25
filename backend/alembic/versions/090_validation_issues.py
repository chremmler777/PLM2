"""090: validation issues (the failure branch of stage 9).

Three new tables (change_validation_issues, change_validation_issue_actions,
change_validation_issue_escalations) and change_attachments.validation_issue_id
(evidence and customer mails filed into an issue). Dialect-neutral: no raw
SQL, server defaults as literals / sa.false(), so the same file runs on
Postgres (prod) and SQLite (tests).

Revision ID: 090
Revises: 089
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "change_validation_issues" not in tables:
        op.create_table(
            "change_validation_issues",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("category", sa.String(30), nullable=False),
            sa.Column("severity", sa.Integer(), nullable=False),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"), nullable=True),
            sa.Column("check_id", sa.Integer(), sa.ForeignKey("validation_checks.id"), nullable=True),
            sa.Column("affected_part_id", sa.Integer(), nullable=True),
            sa.Column("affected_tool_ref", sa.String(120), nullable=True),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("containment", sa.Text(), nullable=True),
            sa.Column("contained_at", sa.DateTime(), nullable=True),
            sa.Column("contained_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("root_cause", sa.Text(), nullable=True),
            sa.Column("root_cause_at", sa.DateTime(), nullable=True),
            sa.Column("root_cause_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("route", sa.String(30), nullable=True),
            sa.Column("route_reason", sa.Text(), nullable=True),
            sa.Column("route_decided_at", sa.DateTime(), nullable=True),
            sa.Column("route_decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("supplier_name", sa.String(120), nullable=True),
            sa.Column("chargeback", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("customer_inform", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("customer_decision", sa.String(20), nullable=True),
            sa.Column("customer_decision_note", sa.Text(), nullable=True),
            sa.Column("customer_decided_at", sa.DateTime(), nullable=True),
            sa.Column("customer_decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("concession_until", sa.Date(), nullable=True),
            sa.Column("new_timing_date", sa.Date(), nullable=True),
            sa.Column("customer_escalation_id", sa.Integer(),
                      sa.ForeignKey("implementation_escalations.id"), nullable=True),
            sa.Column("extra_cost", sa.Numeric(12, 2), nullable=True),
            sa.Column("cost_bearer", sa.String(12), nullable=True),
            sa.Column("fix_quoted_at", sa.DateTime(), nullable=True),
            sa.Column("fix_quoted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("follow_up_change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=True),
            sa.Column("recovery_task_id", sa.Integer(), nullable=True),
            sa.Column("revalidation_task_id", sa.Integer(), nullable=True),
            sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("closure_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("change_id", "number", name="uq_validation_issue_number"),
        )
        op.create_index("ix_change_validation_issues_change_id",
                        "change_validation_issues", ["change_id"])
        op.create_index("ix_change_validation_issues_check_id",
                        "change_validation_issues", ["check_id"])

    if "change_validation_issue_actions" not in tables:
        op.create_table(
            "change_validation_issue_actions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("issue_id", sa.Integer(),
                      sa.ForeignKey("change_validation_issues.id"), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="open"),
            sa.Column("done_at", sa.DateTime(), nullable=True),
            sa.Column("done_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("plan_task_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_change_validation_issue_actions_issue_id",
                        "change_validation_issue_actions", ["issue_id"])

    if "change_validation_issue_escalations" not in tables:
        op.create_table(
            "change_validation_issue_escalations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("issue_id", sa.Integer(),
                      sa.ForeignKey("change_validation_issues.id"), nullable=False),
            sa.Column("level", sa.Integer(), nullable=False),
            sa.Column("trigger", sa.String(30), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("notified", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_change_validation_issue_escalations_issue_id",
                        "change_validation_issue_escalations", ["issue_id"])

    if "validation_issue_id" not in _columns("change_attachments"):
        with op.batch_alter_table("change_attachments") as batch:
            batch.add_column(sa.Column("validation_issue_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_change_attachments_validation_issue_id",
                "change_validation_issues", ["validation_issue_id"], ["id"])
        op.create_index("ix_change_attachments_validation_issue_id",
                        "change_attachments", ["validation_issue_id"])


def downgrade() -> None:
    if "validation_issue_id" in _columns("change_attachments"):
        op.drop_index("ix_change_attachments_validation_issue_id",
                      table_name="change_attachments")
        with op.batch_alter_table("change_attachments") as batch:
            batch.drop_constraint("fk_change_attachments_validation_issue_id",
                                  type_="foreignkey")
            batch.drop_column("validation_issue_id")

    tables = _tables()
    for table, col in (("change_validation_issue_escalations", "issue_id"),
                       ("change_validation_issue_actions", "issue_id")):
        if table in tables:
            op.drop_index(f"ix_{table}_{col}", table_name=table)
            op.drop_table(table)
    if "change_validation_issues" in tables:
        op.drop_index("ix_change_validation_issues_check_id",
                      table_name="change_validation_issues")
        op.drop_index("ix_change_validation_issues_change_id",
                      table_name="change_validation_issues")
        op.drop_table("change_validation_issues")
