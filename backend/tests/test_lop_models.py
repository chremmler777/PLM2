"""Project LOP data model: uniqueness per source and migration 161."""
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.models.lop import (
    LOP_KINDS, LOP_MARKS, LOP_STATUSES, LopLine, LopMeeting, LopMeetingMark,
)
from tests.test_migration_120_sqlite import _cols, _load, _run


def test_vocabularies():
    assert LOP_KINDS == ("task", "sep_item", "risk", "pdb_topic")
    assert LOP_STATUSES == ("new", "open", "in_work", "done_check", "closed")
    assert LOP_MARKS == ("updated", "moved", "escalated", "none")


async def test_line_unique_per_source(session_factory, seed):
    async with session_factory() as s:
        s.add_all([LopLine(project_id=seed["project_id"], kind="sep_item", ref_key="7", created_by=1),
                   LopLine(project_id=seed["project_id"], kind="sep_item", ref_key="7", created_by=1)])
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_two_tasks_without_ref_are_allowed(session_factory, seed):
    async with session_factory() as s:
        s.add_all([LopLine(project_id=seed["project_id"], kind="task", title="A", created_by=1),
                   LopLine(project_id=seed["project_id"], kind="task", title="B", created_by=1)])
        await s.commit()
        n = (await s.execute(sa.select(sa.func.count()).select_from(LopLine))).scalar_one()
    assert n == 2


async def test_line_defaults(session_factory, seed):
    async with session_factory() as s:
        line = LopLine(project_id=seed["project_id"], kind="task", title="A")
        s.add(line)
        await s.commit()
        assert (line.status, line.responsible_is_default, line.due_is_default) == ("new", False, False)
        assert line.created_at is not None and line.created_at.tzinfo is None


async def test_one_mark_per_line_per_meeting(session_factory, seed):
    from datetime import date
    async with session_factory() as s:
        line = LopLine(project_id=seed["project_id"], kind="task", title="A")
        meeting = LopMeeting(project_id=seed["project_id"], held_on=date(2026, 11, 11))
        s.add_all([line, meeting])
        await s.flush()
        s.add_all([LopMeetingMark(meeting_id=meeting.id, line_id=line.id),
                   LopMeetingMark(meeting_id=meeting.id, line_id=line.id, mark="moved")])
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_project_lop_enabled_defaults_false(session_factory, seed):
    from app.models import Project
    async with session_factory() as s:
        assert (await s.get(Project, seed["project_id"])).lop_enabled is False


PRE = """
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE wf_departments (id INTEGER PRIMARY KEY);
CREATE TABLE projects (id INTEGER PRIMARY KEY, code VARCHAR(100), name VARCHAR(255));
INSERT INTO projects VALUES (1, '1748', 'a'), (2, '1864', 'b'), (3, '1994', 'c'),
    (4, '2277', 'd'), (5, '1302', 'e');
"""
NEW_TABLES = ("lop_lines", "lop_comments", "lop_events", "lop_meetings", "lop_meeting_marks")


def test_migration_161_enables_the_four_projects(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()
    m = _load("161_project_lop.py")
    assert (m.revision, m.down_revision) == ("161", "160")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm161.db'}")
    with engine.begin() as conn:
        for stmt in PRE.split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        rows = dict(conn.execute(sa.text("SELECT code, lop_enabled FROM projects")).all())
        assert rows == {"1748": 1, "1864": 1, "1994": 1, "2277": 1, "1302": 0}
        assert set(NEW_TABLES) <= set(sa.inspect(conn).get_table_names())
        # NULL ref_key twice is fine, the same source twice is not
        ins = "INSERT INTO lop_lines (project_id, kind, ref_key, created_at) VALUES (1, :k, :r, '2026-11-11')"
        conn.execute(sa.text(ins), {"k": "task", "r": None})
        conn.execute(sa.text(ins), {"k": "task", "r": None})
        conn.execute(sa.text(ins), {"k": "risk", "r": "3"})
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(sa.text(ins), {"k": "risk", "r": "3"})
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        tables = set(sa.inspect(conn).get_table_names())
        assert not (set(NEW_TABLES) & tables)
        assert "lop_enabled" not in _cols(conn, "projects")
