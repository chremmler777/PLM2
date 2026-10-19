"""148: a named backup per department per project (D2b, Christoph
2026-10-19).

Schema (project_responsibles)
  backup_user_id  FK users.id, nullable: the department's named backup on
                  the project. Tasks go to the responsible; to the backup when
                  the responsible is inactive, left the department or is not
                  set, and to the backup too once a task is overdue.
  user_id         becomes nullable: a row may name only a backup.

Data: none. Every existing row keeps its responsible and has no backup, so
routing is unchanged until Project Management names one; a project without
rows stays legacy (the whole department).

Repeatable: the column is added once, the NOT NULL dropped once.
Downgrade deletes backup-only rows, then drops the column.

Revision ID: 148
Revises: 147
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "148"
down_revision = "147"
branch_labels = None
depends_on = None

TABLE = "project_responsibles"


def _columns() -> dict:
    return {c["name"]: c for c in inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    cols = _columns()
    if "backup_user_id" not in cols:
        op.add_column(TABLE, sa.Column(
            "backup_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    if not cols["user_id"]["nullable"]:
        op.alter_column(TABLE, "user_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    cols = _columns()
    op.execute(sa.text(f"DELETE FROM {TABLE} WHERE user_id IS NULL"))
    if cols["user_id"]["nullable"]:
        op.alter_column(TABLE, "user_id", existing_type=sa.Integer(), nullable=False)
    if "backup_user_id" in cols:
        op.drop_column(TABLE, "backup_user_id")
