"""115 on SQLite: mail_recipients and mail_outbox are created (guarded, so a
second run is a no-op), the unique (project, list, email) holds, and the
downgrade drops both."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

PRE = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE projects (id INTEGER PRIMARY KEY);
CREATE TABLE parts (id INTEGER PRIMARY KEY);
CREATE TABLE part_revisions (id INTEGER PRIMARY KEY);
INSERT INTO projects VALUES (1);
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


def test_115_up_and_down_on_sqlite(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()                  # puts the real alembic into sys.modules, once
    m = _load("115_part_data_mail.py")
    assert (m.revision, m.down_revision) == ("115", "114")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm115.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # guarded
        conn.exec_driver_sql("INSERT INTO mail_recipients (project_id, email) VALUES (1, 'a@b.io')")
        conn.exec_driver_sql("INSERT INTO mail_outbox (project_id, part_id, event) VALUES (1, 1, 'created')")
        row = conn.execute(sa.text("SELECT list_key, active FROM mail_recipients")).one()
        assert tuple(row) == ("part_data", 1)
        assert conn.execute(sa.text("SELECT mail_status FROM mail_outbox")).scalar() == "pending"
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO mail_recipients (project_id, email) VALUES (1, 'a@b.io')")
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        _run(conn, m.downgrade)
        assert {"mail_recipients", "mail_outbox"}.isdisjoint(sa.inspect(conn).get_table_names())
