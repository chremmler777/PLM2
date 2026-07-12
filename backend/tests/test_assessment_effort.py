"""Effort tracking: submit carries effort_hours; summation rolls it up."""
import pytest
from sqlalchemy import select

from tests.conftest import advance_to_assessment
from tests.test_change_scoping import create_change, add_item_and_lead


async def _seed_departments(session_factory):
    """Departments matching TYPE_DISCIPLINES["physical_part"] so the routing
    fallback (no ChangeRoutingStandard configured) produces assessment rows."""
    from app.models.workflow import Department
    async with session_factory() as s:
        for i, n in enumerate(
                ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"]):
            s.add(Department(name=n, flow_type="action", is_active=True, sort_order=i))
        await s.commit()


@pytest.mark.asyncio
async def test_effort_hours_persist_and_roll_up(client, admin_auth, seed, part,
                                                session_factory):
    await _seed_departments(session_factory)
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assessments = res.json()["assessments"]
    assert assessments, "kickoff must create assessment rows"
    dept_id = assessments[0]["department_id"]
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments",
        json={"department_id": dept_id, "verdict": "feasible",
              "effort_hours": 2.5, "notes": "quick check"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["effort_hours"] == 2.5
    res = await client.get(f"/api/v1/changes/{change['id']}/summation",
                           headers=admin_auth)
    body = res.json()
    assert body["total_effort_hours"] == 2.5
    assert {"department_id": dept_id, "effort_hours": 2.5} in body["effort_by_department"]


@pytest.mark.asyncio
async def test_negative_effort_rejected(client, admin_auth, seed, part,
                                        session_factory):
    await _seed_departments(session_factory)
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    dept_id = res.json()["assessments"][0]["department_id"]
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments",
        json={"department_id": dept_id, "verdict": "feasible", "effort_hours": -1},
        headers=admin_auth)
    assert res.status_code == 422
