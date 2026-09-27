"""087: ECR costing to close — plan, offer, release checklist, lessons link.

Five new tables (change_plan_tasks, change_plan_feedback,
change_plan_deviations, change_offers, change_release_checks) and the columns
that carry the new stage state on existing rows. Dialect-neutral: no raw SQL,
server defaults as literals / sa.false(), so the same file runs on Postgres
(prod) and SQLite (tests).

Revision ID: 087
Revises: 086
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None

CHANGE_COLUMNS = [
    ("plan_revision", sa.Integer(), {"nullable": False, "server_default": "0"}),
    ("timing_validated_at", sa.DateTime(), {"nullable": True}),
    ("timing_validated_by", sa.Integer(), {"nullable": True}),
    ("accepted_offer_id", sa.Integer(), {"nullable": True}),
    ("lessons_done_at", sa.DateTime(), {"nullable": True}),
    ("lessons_done_by", sa.Integer(), {"nullable": True}),
    ("lessons_none_reason", sa.Text(), {"nullable": True}),
]
CHANGE_FKS = [
    ("fk_change_requests_timing_validated_by", "timing_validated_by"),
    ("fk_change_requests_lessons_done_by", "lessons_done_by"),
]


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "change_plan_tasks" not in tables:
        op.create_table(
            "change_plan_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("plan", sa.String(10), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("lane", sa.String(80), nullable=True),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"), nullable=True),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("is_idea", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("duration_days", sa.Integer(), nullable=False),
            sa.Column("predecessors", sa.JSON(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("actual_start", sa.Date(), nullable=True),
            sa.Column("actual_finish", sa.Date(), nullable=True),
            sa.Column("baseline_start", sa.Date(), nullable=True),
            sa.Column("baseline_finish", sa.Date(), nullable=True),
            sa.Column("source_position_id", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_change_plan_tasks_change_id", "change_plan_tasks", ["change_id"])

    if "change_plan_feedback" not in tables:
        op.create_table(
            "change_plan_feedback",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"), nullable=False),
            sa.Column("plan_revision", sa.Integer(), nullable=False),
            sa.Column("verdict", sa.String(20), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_change_plan_feedback_change_id", "change_plan_feedback", ["change_id"])

    if "change_plan_deviations" not in tables:
        op.create_table(
            "change_plan_deviations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("change_plan_tasks.id"), nullable=False),
            sa.Column("old_start", sa.Date(), nullable=False),
            sa.Column("old_end", sa.Date(), nullable=False),
            sa.Column("new_start", sa.Date(), nullable=False),
            sa.Column("new_end", sa.Date(), nullable=False),
            sa.Column("slip_days", sa.Integer(), nullable=False),
            sa.Column("finish_impact_days", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(15), nullable=False, server_default="open"),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("escalation_id", sa.Integer(),
                      sa.ForeignKey("implementation_escalations.id"), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_change_plan_deviations_change_id", "change_plan_deviations", ["change_id"])

    if "change_offers" not in tables:
        op.create_table(
            "change_offers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(15), nullable=False, server_default="draft"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column("total_one_time", sa.Numeric(14, 2), nullable=True),
            sa.Column("piece_price_delta", sa.Numeric(12, 4), nullable=True),
            sa.Column("change_note", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("sent_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("received_at", sa.Date(), nullable=True),
            sa.Column("valid_until", sa.Date(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("change_id", "version", name="uq_change_offer_version"),
        )
        op.create_index("ix_change_offers_change_id", "change_offers", ["change_id"])

    if "change_release_checks" not in tables:
        op.create_table(
            "change_release_checks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("check_key", sa.String(40), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="open"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"), nullable=True),
            sa.Column("checked_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("change_id", "check_key", name="uq_change_release_check"),
        )
        op.create_index("ix_change_release_checks_change_id", "change_release_checks", ["change_id"])

    have = _columns("change_requests")
    missing = [(n, t, kw) for n, t, kw in CHANGE_COLUMNS if n not in have]
    if missing:
        names = {n for n, _, _ in missing}
        with op.batch_alter_table("change_requests") as batch:
            for name, type_, kw in missing:
                batch.add_column(sa.Column(name, type_, **kw))
            for fk_name, col in CHANGE_FKS:
                if col in names:
                    batch.create_foreign_key(fk_name, "users", [col], ["id"])

    if "offer_id" not in _columns("change_negotiations"):
        with op.batch_alter_table("change_negotiations") as batch:
            batch.add_column(sa.Column("offer_id", sa.Integer(), nullable=True))

    if "change_id" not in _columns("lessons_learned"):
        with op.batch_alter_table("lessons_learned") as batch:
            batch.add_column(sa.Column("change_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_lessons_learned_change_id", "change_requests",
                ["change_id"], ["id"])
        op.create_index("ix_lessons_learned_change_id", "lessons_learned", ["change_id"])


def downgrade() -> None:
    if "change_id" in _columns("lessons_learned"):
        op.drop_index("ix_lessons_learned_change_id", table_name="lessons_learned")
        with op.batch_alter_table("lessons_learned") as batch:
            batch.drop_constraint("fk_lessons_learned_change_id", type_="foreignkey")
            batch.drop_column("change_id")

    if "offer_id" in _columns("change_negotiations"):
        with op.batch_alter_table("change_negotiations") as batch:
            batch.drop_column("offer_id")

    have = _columns("change_requests")
    with op.batch_alter_table("change_requests") as batch:
        for fk_name, col in CHANGE_FKS:
            if col in have:
                batch.drop_constraint(fk_name, type_="foreignkey")
        for name, _, _ in reversed(CHANGE_COLUMNS):
            if name in have:
                batch.drop_column(name)

    tables = _tables()
    for table in ("change_release_checks", "change_offers",
                  "change_plan_deviations", "change_plan_feedback",
                  "change_plan_tasks"):
        if table in tables:
            op.drop_index(f"ix_{table}_change_id", table_name=table)
            op.drop_table(table)
