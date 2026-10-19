"""119 on SQLite (ECR-solid foundations): new columns, the Toolshop and
Management departments, internal starters, and the backfills:
- sales_owner_id: a customer change raised by a Sales member -> the raiser;
  else the project's Sales responsible; internal / mother plant -> NULL;
- signatures bound to the offer they were given on (accepted, else the
  latest sent);
- old bookings dated at creation, source 'typed'.
Repeatable, and the downgrade drops what it added."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

PRE = """
CREATE TABLE users (id INTEGER PRIMARY KEY, is_active BOOLEAN DEFAULT 1);
CREATE TABLE wf_departments (id INTEGER PRIMARY KEY, name VARCHAR(50) UNIQUE,
    flow_type VARCHAR(20), is_active BOOLEAN, can_start_change BOOLEAN DEFAULT 0,
    sort_order INTEGER, created_at DATETIME);
CREATE TABLE user_departments (user_id INTEGER, department_id INTEGER,
    PRIMARY KEY (user_id, department_id));
CREATE TABLE project_responsibles (id INTEGER PRIMARY KEY, project_id INTEGER,
    department_id INTEGER, user_id INTEGER);
CREATE TABLE change_requests (id INTEGER PRIMARY KEY, project_id INTEGER,
    raised_by INTEGER, customer_relevant BOOLEAN, origin VARCHAR(20),
    pm_signed_by INTEGER, quality_signed_by INTEGER, accepted_offer_id INTEGER);
CREATE TABLE change_offers (id INTEGER PRIMARY KEY, change_id INTEGER,
    version INTEGER, status VARCHAR(15), sent_at DATETIME);
CREATE TABLE implementation_bookings (id INTEGER PRIMARY KEY, change_id INTEGER,
    department_id INTEGER, hours NUMERIC, booked_by INTEGER, booked_at DATETIME);
INSERT INTO users (id) VALUES (1), (2), (3), (4);
INSERT INTO wf_departments (id, name, flow_type, is_active, can_start_change, sort_order)
    VALUES (1, 'Sales', 'action', 1, 1, 1), (2, 'Development', 'action', 1, 0, 7),
           (3, 'Process Engineer', 'action', 1, 0, 6), (4, 'Tool Engineer', 'action', 1, 0, 4),
           (5, 'Quality', 'action', 1, 0, 10);
INSERT INTO user_departments VALUES (1, 1), (2, 2), (3, 1);
INSERT INTO project_responsibles VALUES (1, 20, 1, 3);
-- 10: Sales raised it. 11: Development raised it, project 20 has a Sales
-- responsible (user 3). 12: same but project 21 has none. 13 internal.
-- 14 mother plant
INSERT INTO change_requests VALUES (10, 21, 1, 1, 'customer', NULL, NULL, NULL);
INSERT INTO change_requests VALUES (11, 20, 2, 1, 'customer', 4, 4, 7);
INSERT INTO change_requests VALUES (12, 21, 2, 1, 'customer', 4, NULL, NULL);
INSERT INTO change_requests VALUES (13, 20, 2, 0, 'internal', NULL, NULL, NULL);
INSERT INTO change_requests VALUES (14, 20, 1, 0, 'mother_plant', NULL, NULL, NULL);
INSERT INTO change_offers VALUES (6, 11, 1, 'superseded', '2026-10-01 10:00:00');
INSERT INTO change_offers VALUES (7, 11, 2, 'accepted', '2026-10-05 10:00:00');
INSERT INTO change_offers VALUES (8, 12, 1, 'sent', '2026-10-02 10:00:00');
INSERT INTO change_offers VALUES (9, 12, 2, 'draft', NULL);
INSERT INTO implementation_bookings VALUES (1, 11, 2, 3.5, 2, '2026-10-03 16:20:00');
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


def test_119_up_and_down_on_sqlite(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()                  # puts the real alembic into sys.modules, once
    m = _load("119_ecr_solid_foundations.py")
    assert (m.revision, m.down_revision) == ("119", "118")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm119.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # repeatable
        q = lambda sql: conn.execute(sa.text(sql)).all()
        owners = dict(q("SELECT id, sales_owner_id FROM change_requests"))
        assert owners == {10: 1, 11: 3, 12: None, 13: None, 14: None}
        signed = {r[0]: (r[1], r[2]) for r in q(
            "SELECT id, pm_signed_offer_id, quality_signed_offer_id FROM change_requests")}
        assert signed[11] == (7, 7)        # the accepted offer
        assert signed[12] == (8, None)     # the latest SENT offer, not the draft
        assert signed[10] == (None, None)
        assert dict(q("SELECT id, price_open FROM change_requests"))[11] in (0, False)
        depts = {r[0]: (r[1], r[2]) for r in q(
            "SELECT name, is_active, can_start_internal_change FROM wf_departments")}
        assert depts["Toolshop"][0] and depts["Management"][0]
        internal = {n for n, (_, flag) in depts.items() if flag}
        assert internal == {"Development", "Process Engineer", "Tool Engineer"}
        assert q("SELECT count(*) FROM wf_departments WHERE name='Toolshop'")[0][0] == 1
        assert q("SELECT source, work_date FROM implementation_bookings")[0] == (
            "typed", "2026-10-03")
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        assert "sales_owner_id" not in _cols(conn, "change_requests")
        assert "price_open" not in _cols(conn, "change_requests")
        assert "source" not in _cols(conn, "implementation_bookings")
        assert "can_start_internal_change" not in _cols(conn, "wf_departments")
        # the seeded departments stay (memberships may point at them)
        assert conn.execute(sa.text(
            "SELECT count(*) FROM wf_departments WHERE name='Toolshop'")).scalar() == 1
