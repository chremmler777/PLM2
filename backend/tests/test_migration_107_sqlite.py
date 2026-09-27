"""107 on SQLite: entered_rate and entered_currency on the per-machine rates,
existing rows kept, repeatable, and the downgrade removes them."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa

MIG = Path(os.environ.get("MIG_107") or (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
    / "107_machine_item_rate_entered.py"))

PRE_107 = """
CREATE TABLE cost_sheet_machine_item_rates (id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL, machine_id INTEGER NOT NULL,
    hourly_rate NUMERIC(10, 2) NOT NULL, currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    note TEXT, CONSTRAINT uq_cost_sheet_machine_item_rate UNIQUE (version_id, machine_id));
INSERT INTO cost_sheet_machine_item_rates VALUES (1, 5, 1, 90, 'USD', 'kept');
"""


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig107", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _cols(conn):
    return {c["name"] for c in sa.inspect(conn).get_columns("cost_sheet_machine_item_rates")}


@pytest.mark.skipif(not MIG.exists(), reason="107 lands after 106")
def test_107_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("107", "106")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm107.db'}")
    with engine.begin() as conn:
        for stmt in PRE_107.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
        _run(conn, mod.upgrade)            # guarded
        assert {"entered_rate", "entered_currency"} <= _cols(conn)
        conn.exec_driver_sql("UPDATE cost_sheet_machine_item_rates SET entered_rate = 1557,"
                             " entered_currency = 'MXN' WHERE id = 1")
    with engine.begin() as conn:
        _run(conn, mod.downgrade)
        _run(conn, mod.downgrade)
        assert not {"entered_rate", "entered_currency"} & _cols(conn)
        row = conn.execute(sa.text("SELECT hourly_rate, currency, note FROM "
                                   "cost_sheet_machine_item_rates")).one()
        assert (float(row[0]), row[1], row[2]) == (90.0, "USD", "kept")
        with pytest.raises(sa.exc.IntegrityError):
            conn.exec_driver_sql("INSERT INTO cost_sheet_machine_item_rates (version_id,"
                                 " machine_id, hourly_rate) VALUES (5, 1, 1)")
