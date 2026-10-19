"""146 on SQLite (click-through R38, R25/R31): an open assessment owed by a
retired department moves to its active successor (Developer -> Development),
with its open engine task; answered rows, retired departments without a
successor and a successor already routed in the same stage stay as they are.
Repeatable; the downgrade leaves the data (nothing to undo safely)."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

PRE = """
CREATE TABLE wf_departments (id INTEGER PRIMARY KEY, name VARCHAR(50), is_active BOOLEAN);
INSERT INTO wf_departments VALUES (1, 'Developer', 0), (9, 'R&D', 0),
    (13, 'Logistics', 0), (28, 'Development', 1);
CREATE TABLE wf_instance_tasks (id INTEGER PRIMARY KEY, department_id INTEGER,
    status VARCHAR(20));
INSERT INTO wf_instance_tasks VALUES (543, 1, 'active'), (544, 1, 'approved'),
    (545, 13, 'active'), (546, 9, 'active'), (547, 1, 'waived');
CREATE TABLE change_assessments (id INTEGER PRIMARY KEY, change_id INTEGER,
    department_id INTEGER, stage_order INTEGER, status VARCHAR(20),
    submitted_at DATETIME, wf_instance_task_id INTEGER);
INSERT INTO change_assessments VALUES
    (230, 33, 1, 1, 'pending', NULL, 543),
    (231, 34, 1, 1, 'pending', '2026-10-01 08:00:00', 544),
    (232, 35, 13, 1, 'pending', NULL, 545),
    (233, 36, 9, 1, 'pending', NULL, 546),
    (234, 36, 28, 1, 'pending', NULL, NULL),
    (235, 37, 1, 1, 'pending', NULL, 547);
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


def test_146_moves_open_rows_to_the_successor(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()                  # puts the real alembic into sys.modules, once
    m = _load("146_retired_department_assessments.py")
    assert (m.revision, m.down_revision) == ("146", "145")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm146.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # repeatable
        rows = dict(conn.execute(sa.text(
            "SELECT id, department_id FROM change_assessments")).all())
        tasks = dict(conn.execute(sa.text(
            "SELECT id, department_id FROM wf_instance_tasks")).all())
    assert rows[230] == 28 and tasks[543] == 28      # open: moved with its task
    assert rows[231] == 1 and tasks[544] == 1        # answered: history kept
    assert rows[232] == 13 and tasks[545] == 13      # no successor: untouched
    assert rows[233] == 9 and tasks[546] == 9        # successor already routed
    assert rows[235] == 1 and tasks[547] == 1        # waived through its task
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        assert conn.execute(sa.text(
            "SELECT department_id FROM change_assessments WHERE id = 230")).scalar() == 28
