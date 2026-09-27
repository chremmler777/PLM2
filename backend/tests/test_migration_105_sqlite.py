"""105 on SQLite: cost_sheet_machines, cost_sheet_machine_item_rates and
costing_positions.machine_id are created (keeping existing lines), the
uniques hold, a second upgrade is a no-op, and the downgrade removes them."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa

MIG = Path(os.environ.get("MIG105_PATH") or (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
    / "105_cost_sheet_machines.py"))

PRE_105 = """
CREATE TABLE organizations (id INTEGER PRIMARY KEY);
CREATE TABLE plants (id INTEGER PRIMARY KEY, organization_id INTEGER);
CREATE TABLE cost_sheet_versions (id INTEGER PRIMARY KEY, organization_id INTEGER);
CREATE TABLE cost_sheet_machine_classes (id INTEGER PRIMARY KEY);
CREATE TABLE costing_positions (id INTEGER PRIMARY KEY, label VARCHAR(200),
    machine_class_id INTEGER REFERENCES cost_sheet_machine_classes(id));
INSERT INTO organizations VALUES (1);
INSERT INTO plants VALUES (2, 1);
INSERT INTO cost_sheet_versions VALUES (5, 1);
INSERT INTO costing_positions (id, label) VALUES (7, 'Press');
"""


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig105", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


@pytest.mark.skipif(not MIG.exists(), reason="105 lands after 104")
def test_105_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("105", "104")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm105.db'}")
    with engine.begin() as conn:
        for stmt in PRE_105.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
        _run(conn, mod.upgrade)            # guarded: a second run changes nothing
        insp = sa.inspect(conn)
        assert {"cost_sheet_machines", "cost_sheet_machine_item_rates"} <= set(
            insp.get_table_names())
        assert "machine_id" in {c["name"] for c in insp.get_columns("costing_positions")}
        assert conn.execute(sa.text(
            "SELECT label FROM costing_positions WHERE id = 7")).scalar() == "Press"
        conn.exec_driver_sql(
            "INSERT INTO cost_sheet_machines (id, organization_id, machinedb_id, internal_name,"
            " plant_id, synced_at) VALUES (1, 1, 42, 'P-350', 2, '2026-09-26 10:00:00')")
        assert conn.execute(sa.text(
            "SELECT active FROM cost_sheet_machines WHERE id = 1")).scalar() in (1, True)
        with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
            conn.exec_driver_sql(
                "INSERT INTO cost_sheet_machines (organization_id, machinedb_id, internal_name,"
                " synced_at) VALUES (1, 42, 'dup', '2026-09-26 10:00:00')")
        conn.exec_driver_sql(
            "INSERT INTO cost_sheet_machine_item_rates (version_id, machine_id, hourly_rate)"
            " VALUES (5, 1, 90)")
        assert conn.execute(sa.text(
            "SELECT currency FROM cost_sheet_machine_item_rates")).scalar() == "EUR"
        with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
            conn.exec_driver_sql(
                "INSERT INTO cost_sheet_machine_item_rates (version_id, machine_id, hourly_rate)"
                " VALUES (5, 1, 95)")
        conn.exec_driver_sql("UPDATE costing_positions SET machine_id = 1 WHERE id = 7")
    with engine.begin() as conn:
        _run(conn, mod.downgrade)
        insp = sa.inspect(conn)
        assert "cost_sheet_machines" not in insp.get_table_names()
        assert "cost_sheet_machine_item_rates" not in insp.get_table_names()
        assert "machine_id" not in {c["name"] for c in insp.get_columns("costing_positions")}
        assert conn.execute(sa.text(
            "SELECT label FROM costing_positions WHERE id = 7")).scalar() == "Press"


@pytest.mark.skipif(not MIG.exists(), reason="105 lands after 104")
def test_105_downgrade_drops_the_fk_by_its_real_name(tmp_path):
    """A machine_id FK the database named otherwise (here unnamed, inline)
    is found by inspection, not by a fixed name."""
    mod = _load()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm105b.db'}")
    with engine.begin() as conn:
        for stmt in PRE_105.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
        conn.exec_driver_sql("DROP TABLE costing_positions")
        conn.exec_driver_sql(
            "CREATE TABLE costing_positions (id INTEGER PRIMARY KEY, label VARCHAR(200),"
            " machine_class_id INTEGER REFERENCES cost_sheet_machine_classes(id),"
            " machine_id INTEGER REFERENCES cost_sheet_machines(id))")
        conn.exec_driver_sql("INSERT INTO costing_positions (id, label) VALUES (7, 'Press')")
    with engine.begin() as conn:
        _run(conn, mod.downgrade)
        insp = sa.inspect(conn)
        assert "machine_id" not in {c["name"] for c in insp.get_columns("costing_positions")}
        assert [fk["referred_table"] for fk in insp.get_foreign_keys("costing_positions")] \
            == ["cost_sheet_machine_classes"]
        assert conn.execute(sa.text(
            "SELECT label FROM costing_positions WHERE id = 7")).scalar() == "Press"
