"""113 on SQLite: combined shrinkage on parts and decisions; equal parallel/normal pairs move to
combined; repeatable; the downgrade writes combined back into both directions."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

PRE = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE parts (id INTEGER PRIMARY KEY, part_number VARCHAR(100) NOT NULL,
    tool_shrink_parallel_pct NUMERIC(5,3), tool_shrink_normal_pct NUMERIC(5,3));
INSERT INTO users VALUES (1);
INSERT INTO parts VALUES (1, '199409', 0.65, 0.65);
INSERT INTO parts VALUES (2, '199401', 0.7, 1.0);
INSERT INTO parts VALUES (3, '199402', NULL, NULL);
"""


def _load(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _parts(conn):
    return [tuple(None if v is None else float(v) for v in r[1:]) for r in conn.execute(sa.text(
        "SELECT id, tool_shrink_combined_pct, tool_shrink_parallel_pct, tool_shrink_normal_pct FROM parts ORDER BY id"))]


def test_113_up_and_down_on_sqlite(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()                  # puts the real alembic into sys.modules, once
    m112, m113 = _load("112_tool_shrink_decisions.py"), _load("113_tool_shrink_combined.py")
    assert (m113.revision, m113.down_revision) == ("113", "112")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm113.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
        _run(conn, m112.upgrade)
        conn.exec_driver_sql(
            "INSERT INTO tool_shrink_decisions (tool_id, parallel_pct, normal_pct, source_kind, rationale, decided_by,"
            " decided_at, status) VALUES (1, 0.65, 0.65, 'own', 'why', 1, '2026-10-05', 'current')")
    with engine.begin() as conn:
        _run(conn, m113.upgrade)
        _run(conn, m113.upgrade)            # guarded
        assert _parts(conn) == [(0.65, None, None), (None, 0.7, 1.0), (None, None, None)]
        row = conn.execute(sa.text("SELECT combined_pct, parallel_pct FROM tool_shrink_decisions")).one()
        assert (float(row[0]), row[1]) == (0.65, None)
        # a combined decision has no parallel / normal: the columns accept NULL now
        conn.exec_driver_sql(
            "INSERT INTO tool_shrink_decisions (tool_id, combined_pct, source_kind, rationale, decided_by, decided_at,"
            " status) VALUES (2, 0.9, 'own', 'why', 1, '2026-10-05', 'current')")
    with engine.begin() as conn:
        _run(conn, m113.downgrade)
        _run(conn, m113.downgrade)
        assert [r[1:] for r in _parts_down(conn)] == [(0.65, 0.65), (0.7, 1.0), (None, None)]


def _parts_down(conn):
    return [tuple(None if v is None else float(v) for v in r) for r in conn.execute(sa.text(
        "SELECT id, tool_shrink_parallel_pct, tool_shrink_normal_pct FROM parts ORDER BY id"))]
