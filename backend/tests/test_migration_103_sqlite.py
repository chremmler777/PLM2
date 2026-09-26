"""103 on SQLite: change_gate.decision becomes nullable, a seeded gate nobody
decided (no decider, no time) reads undecided (NULL), a deliberate 'na' stays.
Both ways."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa

MIG = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
       / "103_gate_undecided.py")

PRE_103 = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE change_requests (id INTEGER PRIMARY KEY);
CREATE TABLE change_gate (id INTEGER PRIMARY KEY,
    change_id INTEGER NOT NULL REFERENCES change_requests(id),
    gate_key VARCHAR(20) NOT NULL,
    decision VARCHAR(10) NOT NULL DEFAULT 'na',
    decided_by INTEGER REFERENCES users(id), decided_at DATETIME, remark TEXT);
INSERT INTO users VALUES (1);
INSERT INTO change_requests VALUES (10);
INSERT INTO change_gate (id, change_id, gate_key) VALUES (1, 10, 'release');
INSERT INTO change_gate (id, change_id, gate_key, decision, decided_by, decided_at)
    VALUES (2, 10, 'feasibility', 'na', 1, '2026-09-01 10:00:00');
INSERT INTO change_gate (id, change_id, gate_key, decision, decided_by, decided_at)
    VALUES (3, 10, 'budget', 'yes', 1, '2026-09-01 10:00:00');
"""


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()          # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location("mig103", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _decisions(conn):
    return dict(conn.execute(sa.text(
        "SELECT id, decision FROM change_gate ORDER BY id")).all())


def test_103_up_and_down_on_sqlite(tmp_path):
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("103", "102")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm103.db'}")
    with engine.begin() as conn:
        for stmt in PRE_103.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, mod.upgrade)
        assert _decisions(conn) == {1: None, 2: "na", 3: "yes"}
        # a new seeded gate is undecided without naming a decision
        conn.exec_driver_sql(
            "INSERT INTO change_gate (id, change_id, gate_key) VALUES (4, 10, 'release')")
        assert _decisions(conn)[4] is None
    with engine.begin() as conn:
        _run(conn, mod.downgrade)
        assert _decisions(conn) == {1: "na", 2: "na", 3: "yes", 4: "na"}
