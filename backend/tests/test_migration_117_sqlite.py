"""117 on SQLite: dfm_entries gets deleted_at / deleted_by / delete_reason,
the unnamed unique constraint on supersedes_id (078) becomes a partial unique
index over live rows (guarded, a second run is a no-op), existing rows
survive, and the downgrade restores the plain constraint."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

# dfm_entries as 078 created it: inline (unnamed) UNIQUE on supersedes_id
PRE = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE dfm_topics (id INTEGER PRIMARY KEY);
CREATE TABLE dfm_entries (
    id INTEGER PRIMARY KEY,
    topic_id INTEGER NOT NULL REFERENCES dfm_topics (id),
    party VARCHAR(20) NOT NULL,
    addressed_to JSON NOT NULL,
    note TEXT,
    supersedes_id INTEGER REFERENCES dfm_entries (id),
    recorded_by INTEGER NOT NULL REFERENCES users (id),
    recorded_at DATETIME NOT NULL,
    sent_at DATE,
    kind VARCHAR(20) DEFAULT 'original' NOT NULL,
    reply_to_id INTEGER REFERENCES dfm_entries (id),
    UNIQUE (supersedes_id)
);
CREATE INDEX ix_dfm_entries_topic_id ON dfm_entries (topic_id);
INSERT INTO users VALUES (1);
INSERT INTO dfm_topics VALUES (1);
INSERT INTO dfm_entries (id, topic_id, party, addressed_to, note, recorded_by, recorded_at)
    VALUES (1, 1, 'ktx', '["toolmaker"]', 'v1', 1, '2026-10-01 10:00:00');
INSERT INTO dfm_entries (id, topic_id, party, addressed_to, note, supersedes_id, recorded_by, recorded_at)
    VALUES (2, 1, 'ktx', '["toolmaker"]', 'v2', 1, 1, '2026-10-02 10:00:00')
"""

UPDATE_1 = ("INSERT INTO dfm_entries (topic_id, party, addressed_to, supersedes_id, recorded_by, recorded_at) "
            "VALUES (1, 'ktx', '[\"toolmaker\"]', 1, 1, '2026-10-03 10:00:00')")


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


def _exec(engine, sql):
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def test_117_up_and_down_on_sqlite(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()
    m = _load("117_dfm_entry_delete.py")
    assert (m.revision, m.down_revision) == ("117", "116")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm117.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # guarded
        insp = sa.inspect(conn)
        cols = {c["name"] for c in insp.get_columns("dfm_entries")}
        assert {"deleted_at", "deleted_by", "delete_reason"} <= cols
        assert not [u for u in insp.get_unique_constraints("dfm_entries") if u["column_names"] == ["supersedes_id"]]
        assert m.INDEX in {i["name"] for i in insp.get_indexes("dfm_entries")}
        assert "ix_dfm_entries_topic_id" in {i["name"] for i in insp.get_indexes("dfm_entries")}
        assert [tuple(r) for r in conn.exec_driver_sql("SELECT id, note, supersedes_id FROM dfm_entries")] == [
            (1, "v1", None), (2, "v2", 1)]

    # a second live update of entry 1 is refused; once #2 is deleted it is allowed
    with pytest.raises(sa.exc.IntegrityError):
        _exec(engine, UPDATE_1)
    _exec(engine, "UPDATE dfm_entries SET deleted_at = CURRENT_TIMESTAMP, deleted_by = 1, "
                  "delete_reason = 'too early' WHERE id = 2")
    _exec(engine, UPDATE_1)

    with engine.begin() as conn:
        _run(conn, m.downgrade)            # two rows supersede #1: the plain constraint cannot come back
        _run(conn, m.downgrade)
        insp = sa.inspect(conn)
        assert "deleted_at" not in {c["name"] for c in insp.get_columns("dfm_entries")}
        assert m.INDEX not in {i["name"] for i in insp.get_indexes("dfm_entries")}
        conn.exec_driver_sql("DELETE FROM dfm_entries WHERE id = 2")
        _run(conn, m.downgrade)            # now it can
        uniques = [u for u in sa.inspect(conn).get_unique_constraints("dfm_entries")
                   if u["column_names"] == ["supersedes_id"]]
        assert len(uniques) == 1


def test_117_is_the_only_child_of_116():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()
    children = [p.name for p in VERSIONS.glob("1[0-9][0-9]_*.py") if _load(p.name).down_revision == "116"]
    assert children == ["117_dfm_entry_delete.py"]
