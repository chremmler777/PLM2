"""102 on SQLite: the deviation group table, group_id on the deviations, and
the backfill that groups existing open deviations the way the Timing tab
showed them (a pushed row under the latest own move of its cause). Rows that
fit nowhere stay ungrouped. Both ways and repeatable."""
import importlib.util
import os
from pathlib import Path

import sqlalchemy as sa

MIG = Path(os.environ.get("MIG102_PATH") or (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
    / "102_plan_deviation_groups.py"))

PRE_102 = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE change_requests (id INTEGER PRIMARY KEY);
CREATE TABLE implementation_escalations (id INTEGER PRIMARY KEY);
CREATE TABLE change_plan_deviations (id INTEGER PRIMARY KEY,
    change_id INTEGER, task_id INTEGER, caused_by_task_id INTEGER,
    old_start DATE, old_end DATE, new_start DATE, new_end DATE,
    slip_days INTEGER, finish_impact_days INTEGER, reason TEXT,
    status VARCHAR(15) DEFAULT 'open', decided_by INTEGER, decided_at DATETIME,
    decision_note TEXT, escalation_id INTEGER, created_by INTEGER,
    created_at DATETIME);
INSERT INTO users VALUES (1);
INSERT INTO users VALUES (2);
INSERT INTO change_requests VALUES (10);
INSERT INTO change_requests VALUES (11);
"""

# change 10: move of task 1 (dev 1) pushed 2 and 3 (dev 2, 3); a later move
# of task 1 (dev 4) pushed 2 (dev 5); dev 6 is pushed by task 9, which has
# no own move (stays ungrouped); a fully decided move (dev 7, pushed dev 8)
# gets no group. change 11: a lone open own move (dev 9).
ROWS = [
    (1, 10, 1, None, "supplier late", "open", 1, "2026-09-01 10:00:00"),
    (2, 10, 2, 1, "supplier late", "open", 1, "2026-09-01 10:00:00"),
    (3, 10, 3, 1, "supplier late", "locked", 1, "2026-09-01 10:00:00"),
    (4, 10, 1, None, "second slip", "open", 2, "2026-09-05 10:00:00"),
    (5, 10, 2, 1, "second slip", "open", 2, "2026-09-05 10:00:00"),
    (6, 10, 5, 9, "recovery", "open", 1, "2026-09-06 10:00:00"),
    (7, 10, 7, None, "done", "locked", 1, "2026-09-07 10:00:00"),
    (8, 10, 8, 7, "done", "escalated", 1, "2026-09-07 10:00:00"),
    (9, 11, 4, 4, "own id as cause", "open", 2, None),
]


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig102", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _groups(conn):
    return {r[0]: r[1] for r in conn.execute(sa.text(
        "SELECT id, group_id FROM change_plan_deviations ORDER BY id")).all()}


def test_102_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("102", "101")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm102.db'}")
    with engine.begin() as conn:
        for stmt in PRE_102.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
        for r in ROWS:
            conn.execute(sa.text(
                "INSERT INTO change_plan_deviations (id, change_id, task_id, "
                "caused_by_task_id, old_start, old_end, new_start, new_end, "
                "slip_days, finish_impact_days, reason, status, created_by, "
                "created_at) VALUES (:id, :c, :t, :cb, '2026-10-01', "
                "'2026-10-05', '2026-10-03', '2026-10-07', 2, 2, :r, :s, :u, :at)"),
                dict(zip(("id", "c", "t", "cb", "r", "s", "u", "at"), r)))

    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        g = _groups(conn)
        groups = {r[0]: r for r in conn.execute(sa.text(
            "SELECT id, change_id, root_task_id, reason, status, created_by, "
            "created_at FROM change_plan_deviation_groups")).all()}
        idx = {i["name"] for i in sa.inspect(conn).get_indexes(
            "change_plan_deviations")}
    assert "ix_change_plan_deviations_group_id" in idx
    # first move with both pushed rows (a decided one included)
    assert g[1] is not None and g[1] == g[2] == g[3]
    # the second move of the same task takes the later pushed row
    assert g[4] is not None and g[4] == g[5] and g[4] != g[1]
    # no own move of its cause: ungrouped; a fully decided move: ungrouped
    assert g[6] is None and g[7] is None and g[8] is None
    # a row caused by its own task is its own move
    assert g[9] is not None
    assert len(groups) == 3
    first = groups[g[1]]
    assert first[1:6] == (10, 1, "supplier late", "open", 1)
    assert str(first[6]).startswith("2026-09-01")
    assert groups[g[4]][3:6] == ("second slip", "open", 2)
    assert groups[g[9]][1] == 11 and groups[g[9]][6] is not None

    # repeatable: a second upgrade adds nothing and moves nothing
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        assert _groups(conn) == g
        assert conn.execute(sa.text(
            "SELECT COUNT(*) FROM change_plan_deviation_groups")).scalar() == 3

    with engine.begin() as conn:
        _run(conn, mod.downgrade)
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        assert "change_plan_deviation_groups" not in insp.get_table_names()
        assert "group_id" not in {c["name"] for c in insp.get_columns(
            "change_plan_deviations")}
        assert conn.execute(sa.text(
            "SELECT COUNT(*) FROM change_plan_deviations")).scalar() == len(ROWS)
    # and up again after the way down
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        again = _groups(conn)
    assert _partition(again) == _partition(g)


def _partition(g):
    """Which rows share a group, whatever the group ids are."""
    out: dict = {}
    for did, gid in g.items():
        out.setdefault(gid, set()).add(did)
    return sorted(sorted(v) for k, v in out.items() if k is not None), \
        sorted(did for did, gid in g.items() if gid is None)
