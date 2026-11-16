"""Overdue digest: a passed deadline names who holds the change up
(Christoph 2026-11-16: call out the departments, not only "we are late")."""
from datetime import datetime, timedelta

import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.workflow import Department
from app.services import due_rules
from app.services.overdue_digest import overdue_lines

pytestmark = pytest.mark.asyncio

PAST = datetime.utcnow() - timedelta(days=4)


async def _dept(s, name):
    d = Department(name=name, flow_type="action", is_active=True)
    s.add(d)
    await s.flush()
    return d


async def _change(s, seed, number, **kw):
    c = ChangeRequest(change_number=number, title=f"title {number}", reason="r",
                      change_type="physical_part", project_id=seed["project_id"],
                      raised_by=seed["admin_id"], release_due_date=PAST, **kw)
    s.add(c)
    await s.flush()
    return c


def _assessment(change_id, dept_id, due, **kw):
    return ChangeAssessment(change_id=change_id, department_id=dept_id, status="active",
                            rasic_letter="R", due_date=due, **kw)


async def test_a_passed_deadline_names_the_late_departments_the_reader_does_not_get(session_factory, seed):
    async with session_factory() as s:
        tool = await _dept(s, "Tool Engineer")
        c = await _change(s, seed, "C-N-1")
        s.add(_assessment(c.id, tool.id, due_rules.sub_wd(datetime.utcnow(), 5)))
        await s.commit()
        # this reader gets only what no one department owes (the deadline)
        lines = await overdue_lines(s, keep=lambda dept_id: dept_id is None)
    assert len(lines) == 1
    assert "release deadline passed" in lines[0]
    assert "late in other departments: Tool Engineer assessment" in lines[0]


async def test_a_reader_who_gets_the_late_item_does_not_read_it_twice(session_factory, seed):
    async with session_factory() as s:
        tool = await _dept(s, "Tool Engineer")
        c = await _change(s, seed, "C-N-2")
        s.add(_assessment(c.id, tool.id, due_rules.sub_wd(datetime.utcnow(), 5)))
        await s.commit()
        lines = await overdue_lines(s)
    assert lines[0].count("Tool Engineer assessment") == 1
    assert "late in other departments" not in lines[0] and "waiting on" not in lines[0]


async def test_nothing_late_yet_names_who_the_change_waits_on(session_factory, seed):
    async with session_factory() as s:
        quality = await _dept(s, "Quality")
        c = await _change(s, seed, "C-N-3")
        s.add(_assessment(c.id, quality.id, datetime.utcnow() + timedelta(days=3)))
        await s.commit()
        lines = await overdue_lines(s)
    assert "release deadline passed" in lines[0]
    assert "waiting on: Quality assessment" in lines[0]


async def test_a_change_in_quoting_waits_on_sales(session_factory, seed):
    async with session_factory() as s:
        c = await _change(s, seed, "C-N-4", status="quoting", customer_relevant=True,
                          sales_owner_id=seed["engineer_id"])
        await s.commit()
        await s.refresh(c)
        name = c.sales_owner_name
        lines = await overdue_lines(s)
    assert name and f"waiting on: Sales ({name}): create the quote" in lines[0]


async def test_nobody_open_says_so(session_factory, seed):
    async with session_factory() as s:
        await _change(s, seed, "C-N-5", status="in_assessment")
        await s.commit()
        lines = await overdue_lines(s)
    assert "waiting on: nobody is named" in lines[0]


async def test_a_new_change_waits_on_project_management(session_factory, seed):
    async with session_factory() as s:
        await _change(s, seed, "C-N-6")
        await s.commit()
        lines = await overdue_lines(s)
    assert "waiting on: Project Management: hand over to scoping" in lines[0]
