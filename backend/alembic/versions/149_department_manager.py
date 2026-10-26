"""149: one optional manager per department, for the escalation overview
(Christoph 2026-10-26: "We need managers for an escalation overview").

Schema (wf_departments)
  manager_id  FK users.id, nullable, ON DELETE SET NULL: the department's
              manager. Need not be a member (Christoph manages Process
              Engineer, Tool Engineer and Manufacturing Engineer and is a
              member of Development); one user may manage several
              departments. Managing grants no write rights: it routes the
              overdue digest (overdue_digest, Cut 2) and fills My Tasks'
              "Late in my departments" group, read-only.

Data: none. No department has a manager until an admin names one, so the
digest keeps going to settings.overdue_digest_recipients in full until then.

Repeatable: the column is added once. Downgrade drops it.

Revision ID: 149
Revises: 148
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "149"
down_revision = "148"
branch_labels = None
depends_on = None

TABLE = "wf_departments"
FK = "fk_wf_departments_manager_id_users"


def _columns() -> set:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    if "manager_id" not in _columns():
        op.add_column(TABLE, sa.Column("manager_id", sa.Integer(), nullable=True))
        op.create_foreign_key(FK, TABLE, "users", ["manager_id"], ["id"],
                              ondelete="SET NULL")


def downgrade() -> None:
    if "manager_id" in _columns():
        fks = {f["name"] for f in inspect(op.get_bind()).get_foreign_keys(TABLE)}
        if FK in fks:
            op.drop_constraint(FK, TABLE, type_="foreignkey")
        op.drop_column(TABLE, "manager_id")
