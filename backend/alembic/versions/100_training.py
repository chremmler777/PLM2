"""100: ECR training record (modelled on the TWOS training sign-off).

- training_versions: one published (role, version); the highest is required.
  Version 1 is implicit and has no row.
- training_signoffs: one (user, role, version): trainer, training date,
  tasks-passed timestamp, software_version snapshot, status
  (pending_tasks | active | superseded), carried_from_id for re-training.
- training_attempts: append-only, one row per attempt at one practical task.

Roles are training roles (project_management, sales, engineering,
scheduling, quality, finance), not departments; the mapping is code
(app/services/training.py). Status, trainer source and result are plain
strings so the same file runs on Postgres and on the SQLite test database.

The training gate is an org setting (org_settings.key = 'training_gate') or
the TRAINING_GATE environment variable, default off: no schema needed.

Revision ID: 100
Revises: 099
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "100"
down_revision = "099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "training_versions" not in tables:
        op.create_table(
            "training_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("software_version", sa.String(40), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.Column("published_by", sa.String(255), nullable=False),
            sa.Column("published_by_user_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.UniqueConstraint("role", "version", name="uq_training_version_role_version"),
        )
        op.create_index("ix_training_versions_role", "training_versions",
                        ["role", "version"])

    if "training_signoffs" not in tables:
        op.create_table(
            "training_signoffs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("email_snapshot", sa.String(255), nullable=False, server_default=""),
            sa.Column("display_name", sa.String(255), nullable=True),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("training_date", sa.Date(), nullable=True),
            sa.Column("attested_at", sa.DateTime(), nullable=True),
            sa.Column("trainer_user_id", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=True),
            sa.Column("trainer_name", sa.String(255), nullable=True),
            sa.Column("trainer_source", sa.String(20), nullable=True),
            sa.Column("tasks_passed_at", sa.DateTime(), nullable=True),
            sa.Column("software_version", sa.String(40), nullable=True),
            sa.Column("recorded_by", sa.String(255), nullable=True),
            sa.Column("recorded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=True),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default="pending_tasks"),
            sa.Column("superseded_at", sa.DateTime(), nullable=True),
            sa.Column("carried_from_id", sa.Integer(),
                      sa.ForeignKey("training_signoffs.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("user_id", "role", "version",
                                name="uq_training_signoff_user_role_version"),
        )
        op.create_index("ix_training_signoffs_user", "training_signoffs",
                        ["user_id", "status"])
        op.create_index("ix_training_signoffs_role", "training_signoffs",
                        ["role", "version"])

    if "training_attempts" not in tables:
        op.create_table(
            "training_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("signoff_id", sa.Integer(),
                      sa.ForeignKey("training_signoffs.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("task_key", sa.String(80), nullable=False),
            sa.Column("attempt_no", sa.Integer(), nullable=False),
            sa.Column("result", sa.String(10), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
        )
        op.create_index("ix_training_attempts_signoff", "training_attempts",
                        ["signoff_id", "task_key"])
        op.create_index("ix_training_attempts_user", "training_attempts",
                        ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_training_attempts_user", table_name="training_attempts")
    op.drop_index("ix_training_attempts_signoff", table_name="training_attempts")
    op.drop_table("training_attempts")
    op.drop_index("ix_training_signoffs_role", table_name="training_signoffs")
    op.drop_index("ix_training_signoffs_user", table_name="training_signoffs")
    op.drop_table("training_signoffs")
    op.drop_index("ix_training_versions_role", table_name="training_versions")
    op.drop_table("training_versions")
