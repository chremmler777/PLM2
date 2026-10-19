"""120 on SQLite (ECR-solid C6): the override columns on
change_transition_deviations. Repeatable; existing rows keep guard_key NULL
(they keep waiving what they always did); the downgrade drops the columns."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

PRE = """
CREATE TABLE change_transition_deviations (id INTEGER PRIMARY KEY, change_id INTEGER,
    to_status VARCHAR(30), reason TEXT, status VARCHAR(15), proposed_by INTEGER,
    proposed_at DATETIME, decided_by INTEGER, decided_at DATETIME, decision_note TEXT);
INSERT INTO change_transition_deviations (id, change_id, to_status, reason, status, proposed_by)
    VALUES (1, 5, 'released', 'legacy', 'approved', 2);
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


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def test_120_up_and_down_on_sqlite(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()                  # puts the real alembic into sys.modules, once
    m = _load("120_override_bound_to_rule.py")
    assert (m.revision, m.down_revision) == ("120", "119")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm120.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # repeatable
        assert {"guard_key", "guard_reason", "reason_code"} <= _cols(
            conn, "change_transition_deviations")
        row = conn.execute(sa.text(
            "SELECT status, guard_key FROM change_transition_deviations")).one()
        assert tuple(row) == ("approved", None)   # legacy row untouched
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        _run(conn, m.downgrade)            # repeatable
        assert "guard_key" not in _cols(conn, "change_transition_deviations")
        assert conn.execute(sa.text(
            "SELECT count(*) FROM change_transition_deviations")).scalar() == 1
