"""027: change-scoped wf instances + assessment->task link"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("wf_instances")}
    if "change_id" not in cols:
        # FK lives in the ORM only (SQLite cannot ADD COLUMN with FK)
        op.add_column("wf_instances", sa.Column("change_id", sa.Integer(), nullable=True))
        op.create_index("ix_wf_instances_change_id", "wf_instances", ["change_id"])

    prev = next(c for c in inspect(bind).get_columns("wf_instances")
                if c["name"] == "part_revision_id")
    if not prev["nullable"]:
        with op.batch_alter_table("wf_instances") as batch:
            batch.alter_column("part_revision_id", existing_type=sa.Integer(),
                               nullable=True)

    step = next(c for c in inspect(bind).get_columns("wf_instance_tasks")
                if c["name"] == "step_id")
    if not step["nullable"]:
        with op.batch_alter_table("wf_instance_tasks") as batch:
            batch.alter_column("step_id", existing_type=sa.Integer(), nullable=True)

    cols = {c["name"] for c in inspect(bind).get_columns("change_assessments")}
    if "wf_instance_task_id" not in cols:
        op.add_column("change_assessments",
                      sa.Column("wf_instance_task_id", sa.Integer(), nullable=True))
        idx = {ix["name"] for ix in inspect(bind).get_indexes("change_assessments")}
        if "ix_change_assessments_wf_instance_task_id" not in idx:
            op.create_index("ix_change_assessments_wf_instance_task_id",
                            "change_assessments", ["wf_instance_task_id"], unique=True)


def downgrade() -> None:
    pass  # forward-only, consistent with 023-026
