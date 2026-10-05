"""112 on SQLite: tool_shrink_decisions created, repeatable, and the downgrade drops it."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa

MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "112_tool_shrink_decisions.py"

PRE_112 = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE parts (id INTEGER PRIMARY KEY, part_number VARCHAR(100) NOT NULL);
INSERT INTO users VALUES (1);
INSERT INTO parts VALUES (1, '3501');
"""


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig112", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def test_112_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("112", "111")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm112.db'}")
    with engine.begin() as conn:
        for stmt in PRE_112.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
        _run(conn, mod.upgrade)            # guarded
        conn.exec_driver_sql(
            "INSERT INTO tool_shrink_decisions (tool_id, parallel_pct, normal_pct, source_kind, rationale,"
            " decided_by, decided_at) VALUES (1, 0.8, 1.1, 'supplier', 'why', 1, '2026-10-05')")
        row = conn.execute(sa.text("SELECT status, parallel_pct FROM tool_shrink_decisions")).one()
        assert (row[0], float(row[1])) == ("current", 0.8)
    with engine.begin() as conn:
        _run(conn, mod.downgrade)
        _run(conn, mod.downgrade)
        assert "tool_shrink_decisions" not in sa.inspect(conn).get_table_names()
