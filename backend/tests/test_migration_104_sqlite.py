"""104 on SQLite: one rate per department per plant. Duplicates merged in
every version (the department default kept, else the newest row; its
position cleared), hourly_rate nullable, the unique index with plant NULL
colliding with plant NULL, the open draft seeded with empty rates for every
active department x active plant it does not cover, published versions left
alone. Both ways and repeatable."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa

MIG = Path(os.environ.get("MIG_104") or (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
    / "104_cost_sheet_one_row_per_plant.py"))

PRE_104 = """
CREATE TABLE wf_departments (id INTEGER PRIMARY KEY, name VARCHAR(50), flow_type VARCHAR(20),
    is_active BOOLEAN, sort_order INTEGER);
CREATE TABLE plants (id INTEGER PRIMARY KEY, organization_id INTEGER, name VARCHAR,
    is_active BOOLEAN, currency VARCHAR(3) NOT NULL DEFAULT 'EUR');
CREATE TABLE cost_sheet_versions (id INTEGER PRIMARY KEY, organization_id INTEGER,
    version INTEGER, status VARCHAR(12));
CREATE TABLE cost_sheet_rates (id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES cost_sheet_versions(id) ON DELETE CASCADE,
    department_id INTEGER NOT NULL REFERENCES wf_departments(id),
    position VARCHAR(80), plant_id INTEGER REFERENCES plants(id),
    hourly_rate NUMERIC(10, 2) NOT NULL, currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    min_factor FLOAT, note TEXT);
CREATE INDEX ix_cost_sheet_rates_version_id ON cost_sheet_rates (version_id);
INSERT INTO wf_departments VALUES (1, 'Sales', 'action', 1, 1);
INSERT INTO wf_departments VALUES (2, 'Tool Engineer', 'action', 1, 2);
INSERT INTO wf_departments VALUES (3, 'Scheduling', 'info', 1, 3);
INSERT INTO wf_departments VALUES (4, 'Logistics', 'action', 0, 4);
INSERT INTO plants VALUES (10, 1, 'Weissenburg', 1, 'EUR');
INSERT INTO plants VALUES (11, 1, 'Toccoa', 1, 'USD');
INSERT INTO plants VALUES (12, 1, 'Closed', 0, 'EUR');
INSERT INTO plants VALUES (20, 2, 'Other org', 1, 'EUR');
INSERT INTO cost_sheet_versions VALUES (1, 1, 1, 'published');
INSERT INTO cost_sheet_versions VALUES (2, 1, 2, 'draft');
INSERT INTO cost_sheet_versions VALUES (3, 2, 1, 'draft');
-- published v1: Tool at 10 has a default and a position row, Tool all
-- plants has two position rows only, Sales at 11 is unique
INSERT INTO cost_sheet_rates VALUES (1, 1, 2, 'Engineer', 10, 70, 'EUR', NULL, NULL);
INSERT INTO cost_sheet_rates VALUES (2, 1, 2, NULL, 10, 50, 'EUR', NULL, 'default');
INSERT INTO cost_sheet_rates VALUES (3, 1, 2, 'Engineer', NULL, 65, 'EUR', NULL, NULL);
INSERT INTO cost_sheet_rates VALUES (4, 1, 2, 'Technician', NULL, 40, 'EUR', NULL, 'newest');
INSERT INTO cost_sheet_rates VALUES (5, 1, 1, NULL, 11, 55, 'USD', NULL, NULL);
-- draft v2: Tool all plants, Sales at 10 (twice), nothing for Scheduling
INSERT INTO cost_sheet_rates VALUES (6, 2, 2, NULL, NULL, 52, 'EUR', NULL, NULL);
INSERT INTO cost_sheet_rates VALUES (7, 2, 1, 'Lead', 10, 80, 'EUR', NULL, NULL);
INSERT INTO cost_sheet_rates VALUES (8, 2, 1, 'Clerk', 10, 45, 'EUR', NULL, 'newest');
"""


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig104", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _rates(conn, version_id):
    return {(r[0], r[1]): (r[2], None if r[3] is None else float(r[3]), r[4], r[5])
            for r in conn.exec_driver_sql(
                "SELECT department_id, plant_id, position, hourly_rate, currency, note "
                f"FROM cost_sheet_rates WHERE version_id = {version_id}").all()}


def test_104_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("104", "103")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm104.db'}")
    with engine.begin() as conn:
        for stmt in PRE_104.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)

    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        # published: merged, never seeded
        assert _rates(conn, 1) == {
            (2, 10): (None, 50.0, "EUR", "default"),     # the default row wins
            (2, None): (None, 40.0, "EUR", "newest"),    # else the newest row
            (1, 11): (None, 55.0, "USD", None),
        }
        # draft: merged, then every active department x active plant of the
        # org that has no row gets an empty one in the plant's currency;
        # Tool's all-plants row covers both plants; Logistics is retired,
        # plant 12 closed, plant 20 another org's
        assert _rates(conn, 2) == {
            (2, None): (None, 52.0, "EUR", None),
            (1, 10): (None, 45.0, "EUR", "newest"),
            (1, 11): (None, None, "USD", None),
            (3, 10): (None, None, "EUR", None),
            (3, 11): (None, None, "USD", None),
        }
        # the other org's draft gets its own plant only
        assert _rates(conn, 3) == {(1, 20): (None, None, "EUR", None),
                                   (2, 20): (None, None, "EUR", None),
                                   (3, 20): (None, None, "EUR", None)}
        # the version index survived the table rebuild
        assert "ix_cost_sheet_rates_version_id" in {
            i["name"] for i in sa.inspect(conn).get_indexes("cost_sheet_rates")}
    # one row per department per plant, all plants included
    for plant in ("10", "NULL"):
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "INSERT INTO cost_sheet_rates (version_id, department_id, plant_id, "
                    f"hourly_rate, currency) VALUES (1, 2, {plant}, 1, 'EUR')")
    with engine.begin() as conn:     # another version is another sheet
        conn.exec_driver_sql(
            "INSERT INTO cost_sheet_rates (version_id, department_id, plant_id, "
            "hourly_rate, currency) VALUES (3, 2, NULL, 1, 'EUR')")

    # repeatable
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        assert len(_rates(conn, 2)) == 5

    with engine.begin() as conn:
        _run(conn, mod.downgrade)
    with engine.connect() as conn:
        # the empty rates go (no number to keep), the column is NOT NULL again
        assert set(_rates(conn, 2)) == {(2, None), (1, 10)}
        cols = {c["name"]: c for c in sa.inspect(conn).get_columns("cost_sheet_rates")}
        assert cols["hourly_rate"]["nullable"] is False
        assert conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name = 'uq_cost_sheet_rate_dept_plant'"
        ).first() is None
    with engine.begin() as conn:
        _run(conn, mod.downgrade)

    # and up again
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        assert _rates(conn, 2)[(3, 11)] == (None, None, "USD", None)
    engine.dispose()
