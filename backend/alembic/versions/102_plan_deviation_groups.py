"""102: plan deviation groups, one per edit after the baseline.

A move after "Timing validated" records one deviation per block it touched
(the moved block and every successor it pushed along its links). They are
one story and are decided as one: change_plan_deviation_groups holds the
edit (root block, reason, status, decision, escalation) and
change_plan_deviations.group_id points at it.

Backfill: existing OPEN deviations are grouped the way the Timing tab
already showed them (frontend groupDeviations): a pushed row
(caused_by_task_id set and not its own task) belongs to the latest own move
of its cause recorded before it, on the same change. A group is created only
for a move that still has an open row, and takes the move's reason, author
and time; its rows keep their own status. Rows that fit nowhere (a pushed
row whose cause has no own move) stay ungrouped and are decided one by one,
as before.

Dialect-neutral: the new column has no inline FK (SQLite cannot add one to
an existing table); on Postgres the constraint is added separately.

Revision ID: 102
Revises: 101
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "102"
down_revision = "101"
branch_labels = None
depends_on = None

GROUPS = "change_plan_deviation_groups"
DEVS = "change_plan_deviations"
FK = "fk_change_plan_deviations_group_id"
IX = "ix_change_plan_deviations_group_id"


def _cols(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def _backfill(bind) -> None:
    rows = bind.execute(sa.text(
        f"SELECT id, change_id, task_id, caused_by_task_id, reason, status, "
        f"created_by, created_at, group_id FROM {DEVS} "
        f"ORDER BY change_id, id")).all()
    by_change: dict = {}
    for r in rows:
        by_change.setdefault(r[1], []).append(r)
    for change_id, devs in by_change.items():
        def own(d):
            return d[3] is None or d[3] == d[2]
        members: dict = {}                     # root id -> [row, ...]
        for d in devs:
            if own(d):
                members.setdefault(d[0], [d])
                continue
            roots = [r for r in devs if own(r) and r[2] == d[3] and r[0] < d[0]]
            if roots:
                members.setdefault(roots[-1][0], [roots[-1]]).append(d)
        for root_id, group in members.items():
            root = group[0]
            group = [d for d in group if d[8] is None]
            if root[8] is not None or not any(d[5] == "open" for d in group):
                continue                       # grouped already / all decided
            bind.execute(sa.text(
                f"INSERT INTO {GROUPS} (change_id, root_task_id, reason, status, "
                "created_by, created_at) VALUES (:c, :t, :r, 'open', :u, :at)"),
                {"c": change_id, "t": root[2], "r": root[4] or "",
                 "u": root[6], "at": root[7] or datetime.utcnow()})
            gid = bind.execute(sa.text(
                f"SELECT MAX(id) FROM {GROUPS} WHERE change_id = :c"),
                {"c": change_id}).scalar()
            ids = [d[0] for d in group]
            bind.execute(
                sa.text(f"UPDATE {DEVS} SET group_id = :g WHERE id IN :ids")
                .bindparams(sa.bindparam("ids", expanding=True)),
                {"g": gid, "ids": ids})


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if GROUPS not in tables:
        op.create_table(
            GROUPS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(),
                      sa.ForeignKey("change_requests.id"), nullable=False),
            sa.Column("root_task_id", sa.Integer(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(15), nullable=False,
                      server_default="open"),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("escalation_id", sa.Integer(),
                      sa.ForeignKey("implementation_escalations.id"),
                      nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                      nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_change_plan_deviation_groups_change_id",
                        GROUPS, ["change_id"])
    if DEVS not in tables:
        return
    if "group_id" not in _cols(bind, DEVS):
        op.add_column(DEVS, sa.Column("group_id", sa.Integer(), nullable=True))
        if bind.dialect.name != "sqlite":
            op.create_foreign_key(FK, DEVS, GROUPS, ["group_id"], ["id"])
    if IX not in {i["name"] for i in inspect(bind).get_indexes(DEVS)}:
        op.create_index(IX, DEVS, ["group_id"])
    _backfill(bind)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if DEVS in tables and "group_id" in _cols(bind, DEVS):
        if IX in {i["name"] for i in inspect(bind).get_indexes(DEVS)}:
            op.drop_index(IX, table_name=DEVS)
        if bind.dialect.name != "sqlite":
            fks = {f["name"] for f in inspect(bind).get_foreign_keys(DEVS)}
            if FK in fks:
                op.drop_constraint(FK, DEVS, type_="foreignkey")
        with op.batch_alter_table(DEVS) as batch:
            batch.drop_column("group_id")
    if GROUPS in tables:
        op.drop_index("ix_change_plan_deviation_groups_change_id",
                      table_name=GROUPS)
        op.drop_table(GROUPS)
