"""097: project team, one responsible per department per project
(spec 2026-09-25).

project_responsibles: the main owner of a department's work on a project
(Project Manager, Sales, Development, Tool Engineer, Manufacturing
Engineer, Process Engineer, APQP, Packaging Engineer, Scheduling, Quality,
Finance, ...). Everyone else active in that department is a backup: they
still see and can act, but the row is not theirs to count. No row for a
department on a project -> legacy behaviour (every active member counts as
main). unique(project_id, department_id): one responsible per role.

Dialect-neutral, same file on Postgres and SQLite.

Revision ID: 097
Revises: 096
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "project_responsibles" not in tables:
        op.create_table(
            "project_responsibles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("wf_departments.id"),
                      nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("set_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("set_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("project_id", "department_id", name="uq_project_responsible_role"),
        )
        op.create_index("ix_project_responsibles_project_id", "project_responsibles",
                        ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_responsibles_project_id", table_name="project_responsibles")
    op.drop_table("project_responsibles")
