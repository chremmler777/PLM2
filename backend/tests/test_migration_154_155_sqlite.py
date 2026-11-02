"""154 + 155 on SQLite (Christoph 2026-11-02).

154: change_requests gets hold_review_date / hold_reason; a change on hold
today gets its latest hold's reason and a review date two weeks after that
hold, never before today; others stay empty. Repeatable; downgrade drops.

155: Project Manager is A only on the last Industrialization step of both
ECN templates; other templates and other departments keep their rows.
Repeatable; downgrade puts the three A rows back."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(name):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()                  # puts the real alembic into sys.modules
    spec = importlib.util.spec_from_file_location(name, VERSIONS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _exec(conn, sql):
    for stmt in sql.split(";"):
        if stmt.strip():
            conn.exec_driver_sql(stmt)


def test_154_review_date_for_holds(tmp_path):
    m = _load("154_hold_review_date.py")
    assert (m.revision, m.down_revision) == ("154", "153")
    recent = (date.today() - timedelta(days=3)).isoformat()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm154.db'}")
    with engine.begin() as conn:
        _exec(conn, f"""
CREATE TABLE change_requests (id INTEGER PRIMARY KEY, status VARCHAR(30));
INSERT INTO change_requests VALUES (1, 'on_hold'), (2, 'on_hold'), (3, 'costing');
CREATE TABLE change_changelog (id INTEGER PRIMARY KEY, change_id INTEGER,
    field_name VARCHAR(60), new_value TEXT, notes TEXT, performed_at DATETIME);
INSERT INTO change_changelog VALUES
    (10, 1, 'status', '"on_hold"', 'old hold', '2026-01-05 10:00:00'),
    (11, 1, 'status', '"captured"', NULL, '2026-01-06 10:00:00'),
    (12, 1, 'status', '"on_hold"', 'no PO yet', '{recent} 09:00:00'),
    (13, 2, 'status', '"on_hold"', 'long ago', '2026-01-05 10:00:00');
""")
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # repeatable
        rows = {r[0]: r[1:] for r in conn.execute(sa.text(
            "SELECT id, hold_review_date, hold_reason FROM change_requests")).all()}
    want = (date.today() - timedelta(days=3) + timedelta(days=14)).isoformat()
    assert str(rows[1][0])[:10] == want and rows[1][1] == "no PO yet"
    assert str(rows[2][0])[:10] == date.today().isoformat()   # never escalated at once
    assert rows[3] == (None, None)
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        cols = {c["name"] for c in sa.inspect(conn).get_columns("change_requests")}
    assert "hold_review_date" not in cols and "hold_reason" not in cols


PRE_155 = """
CREATE TABLE wf_departments (id INTEGER PRIMARY KEY, name VARCHAR(50));
INSERT INTO wf_departments VALUES (1, 'Project Manager'), (2, 'Tool Engineer'),
    (3, 'Process Engineer'), (4, 'Quality'), (5, 'Logistics');
CREATE TABLE wf_templates (id INTEGER PRIMARY KEY, name VARCHAR(100));
INSERT INTO wf_templates VALUES (1, 'ECN Implementation (Tool)'),
    (2, 'ECN Implementation (Article)'), (3, 'Other');
CREATE TABLE wf_stages (id INTEGER PRIMARY KEY, template_id INTEGER);
INSERT INTO wf_stages VALUES (1, 1), (2, 2), (3, 3);
CREATE TABLE wf_steps (id INTEGER PRIMARY KEY, stage_id INTEGER, step_name VARCHAR(100));
INSERT INTO wf_steps VALUES
    (11, 1, 'Implement tool change'), (12, 1, 'Adjust process / parameter sheets'),
    (13, 1, 'Clarify inspection plan / PPAP need'), (14, 1, 'Update master data & logistics'),
    (21, 2, 'Implement tool change'), (24, 2, 'Update master data & logistics'),
    (31, 3, 'Implement tool change');
CREATE TABLE wf_step_rasic (step_id INTEGER, department_id INTEGER, rasic_letter VARCHAR(1));
INSERT INTO wf_step_rasic VALUES
    (11, 2, 'R'), (11, 1, 'A'), (12, 3, 'R'), (12, 1, 'A'), (13, 4, 'R'), (13, 1, 'A'),
    (14, 5, 'R'), (14, 1, 'A'), (21, 2, 'R'), (21, 1, 'A'), (24, 5, 'R'), (24, 1, 'A'),
    (31, 1, 'A');
"""


def _pm_a(conn):
    return sorted(conn.execute(sa.text(
        "SELECT step_id FROM wf_step_rasic WHERE department_id = 1 "
        "AND rasic_letter = 'A'")).scalars().all())


def test_155_pm_approves_once(tmp_path):
    m = _load("155_ecn_pm_approves_once.py")
    assert (m.revision, m.down_revision) == ("155", "154")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm155.db'}")
    with engine.begin() as conn:
        _exec(conn, PRE_155)
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # repeatable
        assert _pm_a(conn) == [14, 24, 31]  # last step of both ECN, other template kept
        assert conn.execute(sa.text(
            "SELECT COUNT(*) FROM wf_step_rasic WHERE rasic_letter = 'R'")).scalar() == 6
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        _run(conn, m.downgrade)
        assert _pm_a(conn) == [11, 12, 13, 14, 21, 24, 31]


def test_seed_pm_accountable_on_last_industrialization_step_only():
    from app.services.wf_seed_service import ECN_UMSETZUNG_ARTIKEL, ECN_UMSETZUNG_WERKZEUG
    for tpl in (ECN_UMSETZUNG_ARTIKEL, ECN_UMSETZUNG_WERKZEUG):
        stage = next(s for s in tpl["stages"] if s[0] == "Industrialization")
        pm_a = [step for step, rasic, _ in stage[1]
                if ("Project Manager", "A") in rasic]
        assert pm_a == [stage[1][-1][0]] == ["Update master data & logistics"]
