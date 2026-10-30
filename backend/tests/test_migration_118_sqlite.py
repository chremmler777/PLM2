"""118 on SQLite: ppap_submissions.submitted_by is added nullable (existing
rows untouched), the upgrade repeats safely, and the downgrade drops it."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

PRE = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE ppap_submissions (id INTEGER PRIMARY KEY, revision_id INTEGER NOT NULL,
    status VARCHAR(20), created_by INTEGER NOT NULL REFERENCES users(id));
INSERT INTO users VALUES (1);
INSERT INTO ppap_submissions VALUES (1, 7, 'submitted', 1);
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


def _cols(conn):
    return {c["name"] for c in sa.inspect(conn).get_columns("ppap_submissions")}


def test_118_up_and_down_on_sqlite(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()                  # puts the real alembic into sys.modules, once
    m118 = _load("118_ppap_submitted_by.py")
    assert (m118.revision, m118.down_revision) == ("118", "117a")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm118.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, m118.upgrade)
        _run(conn, m118.upgrade)
        assert "submitted_by" in _cols(conn)
        assert conn.execute(sa.text(
            "SELECT status, submitted_by FROM ppap_submissions")).one() == ("submitted", None)
    with engine.begin() as conn:
        _run(conn, m118.downgrade)
        assert "submitted_by" not in _cols(conn)
        assert conn.execute(sa.text("SELECT count(*) FROM ppap_submissions")).scalar() == 1
