"""151: one optional head per department, next to the manager (Christoph
2026-10-26: "give heads like Russ or Holmes a banner or a headline").

The head is the senior member who leads the department day to day (Russ
Addison heads Manufacturing Engineer, Chris Holmes Process Engineer, Alexa
Earls Logistics); the manager (migration 149) is who escalations go to
(Christoph manages several departments). Both are optional and may be the
same person.

Schema (wf_departments)
  head_id  FK users.id, nullable, ON DELETE SET NULL: the department's
           head. Must be an active member when an admin names it (the
           Departments page, PUT /departments/{id}/head); the page warns
           when the head later turns inactive or leaves the department.
           Being head grants no rights and routes nothing: it is shown.

Data: none. Heads are named by an admin on the Departments page.

Repeatable: the column is added once. Downgrade drops it.

Revision ID: 151
Revises: 150
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "151"
down_revision = "150"
branch_labels = None
depends_on = None

TABLE = "wf_departments"
FK = "fk_wf_departments_head_id_users"


def _columns() -> set:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    if "head_id" not in _columns():
        op.add_column(TABLE, sa.Column("head_id", sa.Integer(), nullable=True))
        op.create_foreign_key(FK, TABLE, "users", ["head_id"], ["id"],
                              ondelete="SET NULL")


def downgrade() -> None:
    if "head_id" in _columns():
        fks = {f["name"] for f in inspect(op.get_bind()).get_foreign_keys(TABLE)}
        if FK in fks:
            op.drop_constraint(FK, TABLE, type_="foreignkey")
        op.drop_column(TABLE, "head_id")
