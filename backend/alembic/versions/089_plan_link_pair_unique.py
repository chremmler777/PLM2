"""089: one link per ordered pair of blocks.

change_plan_links gets a unique index on (change_id, plan, from_task_id,
to_task_id), so two concurrent requests cannot both link the same pair.
Existing duplicates are removed first (the oldest link of a pair stays).
Portable Core only.

Revision ID: 089
Revises: 088
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "089"
down_revision = "088"
branch_labels = None
depends_on = None

INDEX = "uq_change_plan_links_pair"
COLS = ["change_id", "plan", "from_task_id", "to_task_id"]


def duplicate_ids(rows) -> list:
    """rows: (id, change_id, plan, from_task_id, to_task_id). The ids of every
    link but the oldest of its pair. Pure, so the test can call it."""
    keep: dict = {}
    drop = []
    for r in sorted((tuple(x) for x in rows), key=lambda x: x[0]):
        key = r[1:]
        if key in keep:
            drop.append(r[0])
        else:
            keep[key] = r[0]
    return drop


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if "change_plan_links" not in insp.get_table_names():
        return
    if INDEX in {i["name"] for i in insp.get_indexes("change_plan_links")}:
        return
    links = sa.table("change_plan_links", sa.column("id", sa.Integer),
                     *[sa.column(c) for c in COLS])
    rows = bind.execute(sa.select(links.c.id, *[links.c[c] for c in COLS])).all()
    drop = duplicate_ids(rows)
    for i in range(0, len(drop), 500):
        bind.execute(links.delete().where(links.c.id.in_(drop[i:i + 500])))
    op.create_index(INDEX, "change_plan_links", COLS, unique=True)


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if "change_plan_links" in insp.get_table_names() and \
            INDEX in {i["name"] for i in insp.get_indexes("change_plan_links")}:
        op.drop_index(INDEX, table_name="change_plan_links")
