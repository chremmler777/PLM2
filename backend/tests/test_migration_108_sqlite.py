"""108 on SQLite: the six tool tonnage columns on parts, existing rows kept,
repeatable, and the downgrade removes them."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa

MIG = Path(os.environ.get("MIG_108") or (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
    / "108_tool_tonnage_sources.py"))

PRE_108 = """
CREATE TABLE parts (id INTEGER PRIMARY KEY, part_number VARCHAR(100) NOT NULL,
    item_category VARCHAR(30), tool_tonnage_class INTEGER);
INSERT INTO parts VALUES (1, '3454', 'tool', 650);
"""

NEW = {"tool_tonnage_mdb_t", "tool_tonnage_mdb_basis", "tool_tonnage_mdb_machine",
       "tool_tonnage_mdb_at", "tool_tonnage_twos_t", "tool_tonnage_twos_at"}


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig108", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _cols(conn):
    return {c["name"] for c in sa.inspect(conn).get_columns("parts")}


@pytest.mark.skipif(not MIG.exists(), reason="108 lands after 107")
def test_108_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("108", "107")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm108.db'}")
    with engine.begin() as conn:
        for stmt in PRE_108.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
        _run(conn, mod.upgrade)            # guarded
        assert NEW <= _cols(conn)
        conn.exec_driver_sql("UPDATE parts SET tool_tonnage_mdb_t = 450,"
                             " tool_tonnage_mdb_basis = 'assigned' WHERE id = 1")
    with engine.begin() as conn:
        _run(conn, mod.downgrade)
        _run(conn, mod.downgrade)
        assert not NEW & _cols(conn)
        row = conn.execute(sa.text("SELECT part_number, tool_tonnage_class FROM parts")).one()
        assert tuple(row) == ("3454", 650)
