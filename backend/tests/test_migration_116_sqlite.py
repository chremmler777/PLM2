"""116 on SQLite: tool_moldflow is created (guarded, so a second run is a
no-op), defaults hold, one live row per (tool, version, layout) with NULL
layout counted once and a soft-deleted row not blocking, and the downgrade
drops it."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

PRE = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE parts (id INTEGER PRIMARY KEY);
INSERT INTO parts VALUES (1);
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


def _insert(engine, sql):
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def test_116_up_and_down_on_sqlite(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()
    m = _load("116_tool_moldflow.py")
    assert (m.revision, m.down_revision) == ("116", "115")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm116.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # guarded
        conn.exec_driver_sql("INSERT INTO tool_moldflow (tool_part_id) VALUES (1)")
        row = conn.execute(sa.text(
            "SELECT version, status, geometry_status, udb_status, cavity_layout FROM tool_moldflow")).one()
        assert tuple(row) == ("V1", "not_started", "open", "open", None)
    with pytest.raises(sa.exc.IntegrityError):  # NULL layout counts as one value
        _insert(engine, "INSERT INTO tool_moldflow (tool_part_id) VALUES (1)")
    _insert(engine, "INSERT INTO tool_moldflow (tool_part_id, cavity_layout) VALUES (1, '2')")
    _insert(engine, "INSERT INTO tool_moldflow (tool_part_id, cavity_layout) VALUES (1, '2+2')")
    _insert(engine, "INSERT INTO tool_moldflow (tool_part_id, version) VALUES (1, 'V2')")
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, "INSERT INTO tool_moldflow (tool_part_id, cavity_layout) VALUES (1, '2')")
    _insert(engine, "UPDATE tool_moldflow SET deleted_at = CURRENT_TIMESTAMP WHERE cavity_layout = '2'")
    _insert(engine, "INSERT INTO tool_moldflow (tool_part_id, cavity_layout) VALUES (1, '2')")
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        _run(conn, m.downgrade)
        assert "tool_moldflow" not in sa.inspect(conn).get_table_names()


def test_116_is_the_only_child_of_115():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()
    children = [p.name for p in VERSIONS.glob("1[0-9][0-9]_*.py") if _load(p.name).down_revision == "115"]
    assert children == ["116_tool_moldflow.py"]
