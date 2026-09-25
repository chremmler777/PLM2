"""094 runs both ways on SQLite (batch mode for the columns with a foreign
key) and its downgrade collapses the rebuilt chain into 092's single
version."""
import importlib.util
from datetime import date
from pathlib import Path

import sqlalchemy as sa

MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "094_cost_sheet_fixes.py"

PRE_094 = """
CREATE TABLE plants (id INTEGER PRIMARY KEY, organization_id INTEGER, name VARCHAR,
    code VARCHAR, location VARCHAR);
CREATE TABLE cost_sheet_versions (id INTEGER PRIMARY KEY, organization_id INTEGER,
    version INTEGER, status VARCHAR, valid_from DATE, note TEXT, created_at DATETIME,
    published_at DATETIME);
CREATE TABLE cost_sheet_rates (id INTEGER PRIMARY KEY, version_id INTEGER,
    department_id INTEGER, position VARCHAR, plant_id INTEGER, hourly_rate NUMERIC,
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR', min_factor FLOAT, note TEXT);
CREATE TABLE cost_sheet_machine_classes (id INTEGER PRIMARY KEY, organization_id INTEGER,
    name VARCHAR, sort_order INTEGER, is_active BOOLEAN);
CREATE TABLE cost_sheet_machine_rates (id INTEGER PRIMARY KEY, version_id INTEGER,
    machine_class VARCHAR, plant_id INTEGER, currency VARCHAR(3) NOT NULL DEFAULT 'EUR');
CREATE TABLE cost_sheet_sampling_rates (id INTEGER PRIMARY KEY, version_id INTEGER,
    machine_class VARCHAR, plant_id INTEGER, currency VARCHAR(3) NOT NULL DEFAULT 'EUR');
CREATE TABLE cost_sheet_overheads (id INTEGER PRIMARY KEY, plant_id INTEGER, kind VARCHAR);
CREATE TABLE department_rate (id INTEGER PRIMARY KEY, department_id INTEGER,
    plant_id INTEGER, hourly_rate FLOAT, min_factor FLOAT, effective_from DATE);
INSERT INTO plants VALUES (1, 1, 'Toccoa', 'TOC', 'USA');
INSERT INTO department_rate VALUES (1, 7, 1, 50, 0.6, '2026-01-01');
INSERT INTO department_rate VALUES (2, 7, 1, 55, 0.6, '2026-07-01');
INSERT INTO cost_sheet_versions VALUES (1, 1, 1, 'published', '2026-01-01',
    'Migrated from the department rates', '2026-01-01', '2026-01-01');
INSERT INTO cost_sheet_rates VALUES (1, 1, 7, NULL, 1, 55, 'EUR', 0.6, NULL);
INSERT INTO cost_sheet_machine_rates VALUES (1, 1, 'M1', 1, 'EUR');
INSERT INTO cost_sheet_overheads VALUES (1, 1, 'per_hour');
"""


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig094", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def test_094_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm094.db'}")
    with engine.begin() as conn:
        for stmt in PRE_094.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)

    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        for table in ("cost_sheet_machine_rates", "cost_sheet_sampling_rates"):
            assert "machine_class_id" in {c["name"] for c in insp.get_columns(table)}
            fks = insp.get_foreign_keys(table)
            assert [(f["constrained_columns"], f["referred_table"]) for f in fks] == [
                (["machine_class_id"], "cost_sheet_machine_classes")]
        assert conn.exec_driver_sql(
            "SELECT machine_class_id FROM cost_sheet_machine_rates").scalar() is not None
        chain = conn.exec_driver_sql(
            "SELECT version, valid_from FROM cost_sheet_versions ORDER BY version").all()
        assert [(v, str(d)) for v, d in chain] == [(1, "2026-01-01"), (2, "2026-07-01")]
        assert {r[0] for r in conn.exec_driver_sql(
            "SELECT currency FROM cost_sheet_rates")} == {"USD"}

    with engine.begin() as conn:
        _run(conn, mod.downgrade)
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        for table in ("cost_sheet_machine_rates", "cost_sheet_sampling_rates"):
            assert "machine_class_id" not in {c["name"] for c in insp.get_columns(table)}
        assert "currency" not in {c["name"] for c in insp.get_columns("plants")}
        assert "draft_lock" not in {c["name"] for c in insp.get_columns("cost_sheet_versions")}
        # 092's single version is back: the latest rates, valid from the
        # first date, EUR as 092 wrote it
        versions = conn.exec_driver_sql(
            "SELECT id, version, valid_from, note FROM cost_sheet_versions").all()
        assert len(versions) == 1
        vid, number, valid_from, note = versions[0]
        assert (number, str(valid_from), note) == (
            1, str(date(2026, 1, 1)), "Migrated from the department rates")
        assert conn.exec_driver_sql(
            "SELECT hourly_rate, currency FROM cost_sheet_rates WHERE version_id = ?",
            (vid,)).all() == [(55, "EUR")]

    # and up again: the migration is repeatable on SQLite
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    engine.dispose()
