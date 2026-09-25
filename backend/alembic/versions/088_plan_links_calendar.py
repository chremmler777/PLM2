"""088: Gantt 2.0 plan data: links, summaries, constraints, plan calendar.

- change_plan_tasks: parent_id (self FK), constraint_type, constraint_date.
- change_plan_links: FS/SS/FF/SF links with a lag, replacing the
  finish-to-start `predecessors` JSON. Every legacy predecessor whose pair
  has no link yet becomes an FS link (lag 0) and the list is emptied, also
  when the table already existed (a create_all database, a re-run).
- change_requests.plan_calendar (JSON, null = calendar days).
- change_plan_deviations.caused_by_task_id (int, no FK): the block whose
  move dragged this one along (a cascaded deviation).
- Nullability drift from 087: columns the models declare NOT NULL but 087
  created nullable are backfilled and tightened.

Dialect-neutral: SQLAlchemy Core selects/inserts/updates only, batch alter
for SQLite.

Revision ID: 088
Revises: 087
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "088"
down_revision = "087"
branch_labels = None
depends_on = None

PARENT_FK = "fk_change_plan_tasks_parent_id"
# Names an unnamed (SQLite create_all) foreign key the way upgrade names it.
NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s"}

# (table, column, type, backfill value) tightened to NOT NULL
NOT_NULL_FIXES = [
    ("change_plan_tasks", "predecessors", sa.JSON(), "[]"),
    ("change_plan_tasks", "created_at", sa.DateTime(), "now"),
    ("change_plan_tasks", "updated_at", sa.DateTime(), "now"),
    ("change_plan_feedback", "created_at", sa.DateTime(), "now"),
    ("change_plan_deviations", "created_at", sa.DateTime(), "now"),
    ("change_offers", "data", sa.JSON(), "{}"),
    ("change_offers", "created_at", sa.DateTime(), "now"),
    ("change_offers", "updated_at", sa.DateTime(), "now"),
]


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c["name"]: c for c in inspect(op.get_bind()).get_columns(table)}


def predecessor_links(rows, existing=()) -> list[dict]:
    """Legacy predecessor lists as FS links.

    rows: iterables of (id, change_id, plan, predecessors, created_by).
    existing: (from_task_id, to_task_id) pairs already linked; a pair linked
    in either direction is skipped (a reverse link would make a loop).
    Only ids of the same change and plan count; self links, unknown ids,
    duplicates and junk values are dropped. Pure, so the test can call it."""
    rows = [tuple(r) for r in rows]
    where = {r[0]: (r[1], r[2]) for r in rows}
    linked = {frozenset(p) for p in existing}
    out, seen = [], set()
    for tid, change_id, plan, preds, created_by in rows:
        for p in preds or []:
            try:
                pid = int(p)
            except (TypeError, ValueError):
                continue
            if pid == tid or where.get(pid) != (change_id, plan):
                continue
            pair = frozenset((pid, tid))
            if pair in seen or pair in linked:
                continue
            seen.add(pair)
            out.append({"change_id": change_id, "plan": plan,
                        "from_task_id": pid, "to_task_id": tid, "type": "FS",
                        "lag_days": 0, "created_by": created_by})
    return out


def _tasks_t():
    return sa.table("change_plan_tasks", sa.column("id", sa.Integer),
                    sa.column("change_id", sa.Integer), sa.column("plan", sa.String),
                    sa.column("predecessors", sa.JSON),
                    sa.column("created_by", sa.Integer))


def _links_t():
    return sa.table("change_plan_links", sa.column("change_id", sa.Integer),
                    sa.column("plan", sa.String), sa.column("from_task_id", sa.Integer),
                    sa.column("to_task_id", sa.Integer), sa.column("type", sa.String),
                    sa.column("lag_days", sa.Integer), sa.column("created_by", sa.Integer),
                    sa.column("created_at", sa.DateTime))


def convert_predecessors(bind) -> int:
    """Every legacy predecessor without a link for its pair becomes an FS
    link; every non-empty list is emptied afterwards."""
    tasks, links = _tasks_t(), _links_t()
    rows = bind.execute(sa.select(tasks.c.id, tasks.c.change_id, tasks.c.plan,
                                  tasks.c.predecessors, tasks.c.created_by)).all()
    existing = bind.execute(sa.select(links.c.from_task_id, links.c.to_task_id)).all()
    new = predecessor_links(rows, existing)
    if new:
        now = datetime.utcnow()
        bind.execute(links.insert(), [{**n, "created_at": now} for n in new])
    for r in rows:
        if r[3]:
            bind.execute(tasks.update().where(tasks.c.id == r[0])
                         .values(predecessors=[]))
    return len(new)


def upgrade() -> None:
    bind = op.get_bind()
    have = _columns("change_plan_tasks")
    if "parent_id" not in have:
        with op.batch_alter_table("change_plan_tasks") as batch:
            batch.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("constraint_type", sa.String(4), nullable=True))
            batch.add_column(sa.Column("constraint_date", sa.Date(), nullable=True))
            batch.create_foreign_key(
                PARENT_FK, "change_plan_tasks", ["parent_id"], ["id"])

    if "change_plan_links" not in _tables():
        op.create_table(
            "change_plan_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("plan", sa.String(10), nullable=False),
            sa.Column("from_task_id", sa.Integer(), sa.ForeignKey("change_plan_tasks.id"), nullable=False),
            sa.Column("to_task_id", sa.Integer(), sa.ForeignKey("change_plan_tasks.id"), nullable=False),
            sa.Column("type", sa.String(2), nullable=False, server_default="FS"),
            sa.Column("lag_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_change_plan_links_change_id", "change_plan_links", ["change_id"])

    if "plan_calendar" not in _columns("change_requests"):
        with op.batch_alter_table("change_requests") as batch:
            batch.add_column(sa.Column("plan_calendar", sa.JSON(), nullable=True))

    if "change_plan_deviations" in _tables() and \
            "caused_by_task_id" not in _columns("change_plan_deviations"):
        with op.batch_alter_table("change_plan_deviations") as batch:
            batch.add_column(sa.Column("caused_by_task_id", sa.Integer(), nullable=True))

    convert_predecessors(bind)

    now = datetime.utcnow()
    for table, col, type_, fill in NOT_NULL_FIXES:
        if table not in _tables():
            continue
        cols = _columns(table)
        if col not in cols or not cols[col]["nullable"]:
            continue
        t = sa.table(table, sa.column(col, type_))
        value = [] if fill == "[]" else {} if fill == "{}" else now
        bind.execute(t.update().where(t.c[col].is_(None)).values({col: value}))
        with op.batch_alter_table(table) as batch:
            batch.alter_column(col, existing_type=type_, nullable=False)


def _parent_fk_name():
    """The parent_id foreign key's name: ours from upgrade, the dialect's
    default on a create_all Postgres database, None when unnamed (SQLite)."""
    for fk in inspect(op.get_bind()).get_foreign_keys("change_plan_tasks"):
        if fk.get("constrained_columns") == ["parent_id"]:
            return fk.get("name") or None
    return None


def downgrade() -> None:
    bind = op.get_bind()
    for table, col, type_, _ in reversed(NOT_NULL_FIXES):
        if table in _tables() and col in _columns(table):
            with op.batch_alter_table(table) as batch:
                batch.alter_column(col, existing_type=type_, nullable=True)

    if "change_plan_links" in _tables():
        # FS links back into the legacy lists, so 087 code keeps its links.
        # Every list is reset first: a stale list must not survive next to
        # the links it was converted into.
        links = sa.table("change_plan_links", sa.column("from_task_id", sa.Integer),
                         sa.column("to_task_id", sa.Integer), sa.column("type", sa.String))
        tasks = sa.table("change_plan_tasks", sa.column("id", sa.Integer),
                         sa.column("predecessors", sa.JSON))
        bind.execute(tasks.update().values(predecessors=[]))
        preds: dict[int, list[int]] = {}
        for f, t, typ in bind.execute(sa.select(links.c.from_task_id, links.c.to_task_id,
                                                links.c.type)).all():
            if typ == "FS":
                preds.setdefault(t, []).append(f)
        for tid, ps in preds.items():
            bind.execute(tasks.update().where(tasks.c.id == tid).values(predecessors=ps))
        op.drop_index("ix_change_plan_links_change_id", table_name="change_plan_links")
        op.drop_table("change_plan_links")

    if "change_plan_deviations" in _tables() and \
            "caused_by_task_id" in _columns("change_plan_deviations"):
        with op.batch_alter_table("change_plan_deviations") as batch:
            batch.drop_column("caused_by_task_id")

    if "plan_calendar" in _columns("change_requests"):
        with op.batch_alter_table("change_requests") as batch:
            batch.drop_column("plan_calendar")

    if "parent_id" in _columns("change_plan_tasks"):
        name = _parent_fk_name()
        # An unnamed FK (SQLite create_all) gets our name from the naming
        # convention while batch mode reflects the table; batch recreates
        # the table without it either way once the column is gone.
        with op.batch_alter_table("change_plan_tasks",
                                  naming_convention=NAMING) as batch:
            if name is not None:
                batch.drop_constraint(name, type_="foreignkey")
            elif bind.dialect.name == "sqlite":
                batch.drop_constraint(PARENT_FK, type_="foreignkey")
            batch.drop_column("constraint_date")
            batch.drop_column("constraint_type")
            batch.drop_column("parent_id")
