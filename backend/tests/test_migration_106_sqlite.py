"""106 on SQLite: plants.local_currency, cost_sheet_versions.fx_rates, the
entered rate and currency on rate and machine rows; Silao becomes USD with
MXN as its local currency (once), its empty draft rows follow; published
rows stay as they are. Both ways and repeatable, with 104's unique index
surviving the table rebuild."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa

MIG = Path(os.environ.get("MIG_106") or (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
    / "106_cost_sheet_dual_currency.py"))

PRE_106 = """
CREATE TABLE plants (id INTEGER PRIMARY KEY, organization_id INTEGER, name VARCHAR,
    code VARCHAR, location VARCHAR, is_active BOOLEAN,
    currency VARCHAR(3) NOT NULL DEFAULT 'EUR');
CREATE TABLE cost_sheet_versions (id INTEGER PRIMARY KEY, organization_id INTEGER,
    version INTEGER, status VARCHAR(12), draft_lock INTEGER);
CREATE UNIQUE INDEX uq_cost_sheet_one_draft ON cost_sheet_versions (organization_id, draft_lock);
CREATE TABLE cost_sheet_rates (id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES cost_sheet_versions(id) ON DELETE CASCADE,
    department_id INTEGER NOT NULL, position VARCHAR(80), plant_id INTEGER,
    hourly_rate NUMERIC(10, 2), currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    min_factor FLOAT, note TEXT);
CREATE UNIQUE INDEX uq_cost_sheet_rate_dept_plant
    ON cost_sheet_rates (version_id, department_id, coalesce(plant_id, 0));
CREATE TABLE cost_sheet_machine_rates (id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL,
    plant_id INTEGER, machine_class_id INTEGER, machine_class VARCHAR(40) NOT NULL,
    machine_ref VARCHAR(80), tonnage_min INTEGER, tonnage_max INTEGER,
    hourly_rate NUMERIC(10, 2) NOT NULL, currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    note TEXT);
INSERT INTO plants VALUES (1, 1, 'USA Toccoa', 'usa-toccoa', 'Toccoa, GA, USA', 1, 'USD');
INSERT INTO plants VALUES (2, 1, 'Weissenburg', 'WUG', 'DE', 1, 'EUR');
INSERT INTO plants VALUES (3, 1, 'Silao Mexico', 'SIL', 'MX', 1, 'EUR');
INSERT INTO plants VALUES (4, 1, 'Silaoville', 'SV', 'Nowhere', 1, 'EUR');
INSERT INTO cost_sheet_versions VALUES (1, 1, 1, 'published', NULL);
INSERT INTO cost_sheet_versions VALUES (2, 1, 2, 'draft', 1);
INSERT INTO cost_sheet_rates VALUES (1, 1, 5, NULL, 3, 50, 'EUR', NULL, NULL);
INSERT INTO cost_sheet_rates VALUES (2, 2, 5, NULL, 3, NULL, 'EUR', NULL, NULL);
INSERT INTO cost_sheet_rates VALUES (3, 2, 6, NULL, 3, 44, 'EUR', NULL, 'typed');
INSERT INTO cost_sheet_rates VALUES (4, 2, 5, NULL, 2, NULL, 'EUR', NULL, NULL);
"""


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig106", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def _dup_refused(engine):
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO cost_sheet_rates (version_id, department_id, "
                                 "plant_id, hourly_rate, currency) VALUES (1, 5, 3, 1, 'USD')")


def test_106_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("106", "105")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm106.db'}")
    with engine.begin() as conn:
        for stmt in PRE_106.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)

    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        assert "local_currency" in _cols(conn, "plants")
        assert "fx_rates" in _cols(conn, "cost_sheet_versions")
        for t in ("cost_sheet_rates", "cost_sheet_machine_rates"):
            assert {"entered_rate", "entered_currency"} <= _cols(conn, t)
        # Silao by name/code/location as a whole word, not "Silaoville"
        assert {r[0]: (r[1], r[2]) for r in conn.exec_driver_sql(
            "SELECT id, currency, local_currency FROM plants").all()} == {
            1: ("USD", None), 2: ("EUR", None), 3: ("USD", "MXN"), 4: ("EUR", None)}
        # the draft's empty Silao row follows the plant; a typed rate and the
        # published version keep their currency
        assert dict(conn.exec_driver_sql(
            "SELECT id, currency FROM cost_sheet_rates").all()) == {
            1: "EUR", 2: "USD", 3: "EUR", 4: "EUR"}
    _dup_refused(engine)

    # repeatable; a plant that already has a local currency is left alone
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE plants SET currency = 'MXN' WHERE id = 3")
        _run(conn, mod.upgrade)
    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT currency FROM plants WHERE id = 3").scalar() == "MXN"

    with engine.begin() as conn:
        _run(conn, mod.downgrade)
    with engine.connect() as conn:
        assert "local_currency" not in _cols(conn, "plants")
        assert "fx_rates" not in _cols(conn, "cost_sheet_versions")
        assert "entered_rate" not in _cols(conn, "cost_sheet_rates")
        assert "entered_currency" not in _cols(conn, "cost_sheet_machine_rates")
        assert conn.exec_driver_sql("SELECT count(*) FROM cost_sheet_rates").scalar() == 4
    _dup_refused(engine)          # 104's index survived the rebuild
    with engine.begin() as conn:
        _run(conn, mod.downgrade)
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
    engine.dispose()
