"""101 on SQLite: Toccoa relabelled USD (094's US/USA match missed "Toccoa,
GA"), actual costs backfilled with the costing currency, duplicate standing
effort rows merged, and the partial unique index keeping it that way. Both
ways and repeatable."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

MIG = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
       / "101_actual_cost_currency_standing_rows.py")

PRE_101 = """
CREATE TABLE plants (id INTEGER PRIMARY KEY, organization_id INTEGER, name VARCHAR,
    code VARCHAR, location VARCHAR, currency VARCHAR(3) NOT NULL DEFAULT 'EUR');
CREATE TABLE projects (id INTEGER PRIMARY KEY, plant_id INTEGER, name VARCHAR);
CREATE TABLE change_requests (id INTEGER PRIMARY KEY, project_id INTEGER);
CREATE TABLE change_affected_plants (change_id INTEGER, plant_id INTEGER,
    PRIMARY KEY (change_id, plant_id));
CREATE TABLE change_actual_costs (id INTEGER PRIMARY KEY, change_id INTEGER,
    category VARCHAR(12), amount NUMERIC(12, 2), cost_date DATE, created_by INTEGER);
CREATE TABLE costing_positions (id INTEGER PRIMARY KEY, change_id INTEGER,
    department_id INTEGER, label VARCHAR, tag VARCHAR, kind VARCHAR, hours NUMERIC,
    est_cost NUMERIC, notes TEXT, labour_position VARCHAR, lead_time_days INTEGER,
    lead_time_unit VARCHAR, created_by INTEGER, updated_at DATETIME);
CREATE TABLE costing_offers (id INTEGER PRIMARY KEY, position_id INTEGER);
INSERT INTO plants VALUES (1, 1, 'Toccoa', 'TOC', 'Toccoa, GA', 'EUR');
INSERT INTO plants VALUES (2, 1, 'Weissenburg', 'WUG', 'DE', 'EUR');
INSERT INTO plants VALUES (3, 1, 'Plant 3', 'P3', 'toccoa county', 'EUR');
INSERT INTO projects VALUES (1, 1, 'Atlas');
INSERT INTO projects VALUES (2, 2, 'G65');
INSERT INTO change_requests VALUES (10, 1);
INSERT INTO change_requests VALUES (11, 2);
INSERT INTO change_requests VALUES (12, 2);
INSERT INTO change_affected_plants VALUES (12, 1);
INSERT INTO change_actual_costs VALUES (1, 10, 'external', 100, '2026-09-01', 1);
INSERT INTO change_actual_costs VALUES (2, 11, 'external', 200, '2026-09-01', 1);
INSERT INTO change_actual_costs VALUES (3, 12, 'scrap', 300, '2026-09-01', 1);
INSERT INTO costing_positions VALUES (1, 10, 5, 'Support', NULL, 'support_effort', 8,
    NULL, NULL, NULL, NULL, 'calendar_days', 1, '2026-09-16 22:03:03');
INSERT INTO costing_positions VALUES (2, 10, 5, 'Support', NULL, 'support_effort', 12,
    NULL, 'typed last', 'Engineer', NULL, 'calendar_days', 1, '2026-09-16 22:03:04');
INSERT INTO costing_positions VALUES (3, 10, 5, 'Drawing', NULL, 'own_time', 2,
    NULL, NULL, NULL, NULL, 'calendar_days', 1, '2026-09-16 22:03:05');
INSERT INTO costing_positions VALUES (4, 10, 5, 'Drawing', NULL, 'own_time', 2,
    NULL, NULL, NULL, NULL, 'calendar_days', 1, '2026-09-16 22:03:06');
INSERT INTO costing_positions VALUES (5, 10, 6, 'Effort', NULL, 'internal_effort', 3,
    NULL, NULL, NULL, NULL, 'calendar_days', 1, '2026-09-16 22:03:07');
"""


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig101", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def test_101_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("101", "100")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm101.db'}")
    with engine.begin() as conn:
        for stmt in PRE_101.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)

    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        # Toccoa by name and by location, nothing else
        assert dict(conn.exec_driver_sql(
            "SELECT id, currency FROM plants").all()) == {1: "USD", 2: "EUR", 3: "USD"}
        # project plant (10: Toccoa), project plant (11: DE), the only
        # affected plant wins over the project's (12: Toccoa)
        assert dict(conn.exec_driver_sql(
            "SELECT id, currency FROM change_actual_costs").all()) == {
            1: "USD", 2: "EUR", 3: "USD"}
        rows = conn.exec_driver_sql(
            "SELECT id, kind, hours, notes, labour_position FROM costing_positions "
            "ORDER BY id").all()
        # the oldest standing row stays, with what was typed last; own_time
        # lines may repeat
        assert [(r[0], r[1]) for r in rows] == [
            (1, "support_effort"), (3, "own_time"), (4, "own_time"),
            (5, "internal_effort")]
        assert (float(rows[0][2]), rows[0][3], rows[0][4]) == (12.0, "typed last", "Engineer")
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO costing_positions (change_id, department_id, label, kind, "
                "created_by) VALUES (10, 5, 'dup', 'support_effort', 1)")

    with engine.begin() as conn:
        _run(conn, mod.downgrade)
    with engine.connect() as conn:
        insp = sa.inspect(conn)
        assert "currency" not in {c["name"] for c in insp.get_columns("change_actual_costs")}
        assert mod.INDEX not in {i["name"] for i in insp.get_indexes("costing_positions")}
        # the relabel stays
        assert conn.exec_driver_sql(
            "SELECT currency FROM plants WHERE id = 1").scalar() == "USD"

    # and up again: repeatable
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    engine.dispose()
