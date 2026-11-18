"""Project LOP for a department manager (Christoph 2026-11-18): the manager
sees every open line of the departments they manage, whoever owns it."""
import pytest
from sqlalchemy import select

from app.models.workflow import Department

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


async def _manage(session_factory, department_id, user_id):
    async with session_factory() as s:
        d = (await s.execute(select(Department).where(Department.id == department_id))).scalar_one()
        d.manager_id = user_id
        await s.commit()


async def test_not_a_manager_gets_no_group(client, quality_auth, line):
    r = await client.get(f"{BASE}/departments/mine", headers=quality_auth)
    assert r.status_code == 200, r.text
    assert r.json() == {"departments": [], "lines": []}


async def test_manager_sees_every_open_line_of_the_department(
        client, pm_auth, outsider_auth, lop_project, line, session_factory):
    # the outsider is not on the project team and owns nothing, but manages APQP
    await _manage(session_factory, lop_project.apqp_id, lop_project.outsider_id)
    other = await client.post(f"{BASE}/projects/{lop_project.id}/lines", headers=pm_auth,
                              json={"title": "Sales task", "department_id": lop_project.sales_dept_id,
                                    "due_date": "2026-11-20"})
    assert other.status_code == 201, other.text
    b = (await client.get(f"{BASE}/departments/mine", headers=outsider_auth)).json()
    assert [d["name"] for d in b["departments"]] == ["APQP"]
    assert [x["id"] for x in b["lines"]] == [line]              # not the Sales line
    row = b["lines"][0]
    assert row["project_code"] == "lop1" and row["department_name"] == "APQP"
    assert row["responsible_id"] == lop_project.quality_user_id and row["responsible_name"]
    assert row["can_manage"] is False and row["can_report"] is False   # view only
    # the manager's own My Tasks LOP group stays empty: the line is not theirs
    assert (await client.get(f"{BASE}/mine", headers=outsider_auth)).json() == []


async def test_closed_lines_leave_the_manager_group(
        client, pm_auth, outsider_auth, lop_project, line, session_factory):
    await _manage(session_factory, lop_project.apqp_id, lop_project.outsider_id)
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "closed"})
    assert r.status_code == 200, r.text
    assert (await client.get(f"{BASE}/departments/mine", headers=outsider_auth)).json()["lines"] == []
