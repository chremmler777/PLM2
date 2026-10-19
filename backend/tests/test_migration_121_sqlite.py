"""121 on SQLite (ECR-solid C7): change_validation_issues gets
customer_decided_as_quality, backfilled from the decider's real Quality
membership (the rule release used until now). Repeatable; downgrade drops it."""
import sqlalchemy as sa

from tests.test_migration_120_sqlite import _cols, _load, _run

PRE = """
CREATE TABLE wf_departments (id INTEGER PRIMARY KEY, name VARCHAR(100), is_active BOOLEAN);
CREATE TABLE user_departments (id INTEGER PRIMARY KEY, user_id INTEGER, department_id INTEGER);
CREATE TABLE change_validation_issues (id INTEGER PRIMARY KEY, change_id INTEGER,
    status VARCHAR(20), customer_decided_by INTEGER);
INSERT INTO wf_departments VALUES (1, 'Quality', 1), (2, 'Sales', 1);
INSERT INTO user_departments VALUES (1, 10, 1), (2, 20, 2);
INSERT INTO change_validation_issues VALUES (1, 5, 'accepted', 10), (2, 5, 'accepted', 20),
    (3, 5, 'open', NULL);
"""


def test_121_up_and_down_on_sqlite(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()
    m = _load("121_concession_decided_as_quality.py")
    assert (m.revision, m.down_revision) == ("121", "120")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm121.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)              # repeatable
        rows = dict(conn.execute(sa.text(
            "SELECT id, customer_decided_as_quality FROM change_validation_issues")).all())
        assert rows == {1: 1, 2: 0, 3: None}
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        _run(conn, m.downgrade)
        assert "customer_decided_as_quality" not in _cols(conn, "change_validation_issues")
