"""Meeting module: CRUD, PM authz, decide side effects."""
import pytest

from tests.conftest import login, ENGINEER_PASSWORD
from tests.test_change_scoping import create_change, add_item_and_lead


async def post_meeting(client, auth, change_id, **overrides):
    body = {"participants": [{"name": "PM Jane"}, {"name": "Customer Rep"}],
            "notes": "Initial scope clarification",
            "selected_department_ids": [], **overrides}
    return await client.post(f"/api/v1/changes/{change_id}/meetings",
                             json=body, headers=auth)


@pytest.mark.asyncio
async def test_meeting_crud_and_needs_info(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    res = await post_meeting(client, admin_auth, change["id"])
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    res = await client.patch(f"/api/v1/changes/{change['id']}/meetings/{mid}",
                             json={"notes": "updated"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["notes"] == "updated"
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "needs_info"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["decision"] == "needs_info"
    # decided meetings are immutable
    res = await client.patch(f"/api/v1/changes/{change['id']}/meetings/{mid}",
                             json={"notes": "nope"}, headers=admin_auth)
    assert res.status_code == 400
    # change unaffected by needs_info
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "captured"
    # list shows the meeting
    res = await client.get(f"/api/v1/changes/{change['id']}/meetings", headers=admin_auth)
    assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_proceed_kicks_off_assessment(client, admin_auth, seed, part,
                                            session_factory):
    from sqlalchemy import select
    from app.models.workflow import Department
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    async with session_factory() as s:
        # Fresh test DB has no departments seeded; create a couple so the
        # scoping meeting has real department ids to select.
        s.add_all([Department(name="Quality", flow_type="action", is_active=True),
                   Department(name="Sales", flow_type="action", is_active=True)])
        await s.commit()
    async with session_factory() as s:
        dept_ids = [d for (d,) in await s.execute(select(Department.id))][:2]
    res = await post_meeting(client, admin_auth, change["id"],
                             selected_department_ids=dept_ids)
    mid = res.json()["id"]
    # proceed without departments is rejected on a fresh meeting
    res2 = await post_meeting(client, admin_auth, change["id"])
    res3 = await client.post(
        f"/api/v1/changes/{change['id']}/meetings/{res2.json()['id']}/decide",
        json={"decision": "proceed"}, headers=admin_auth)
    assert res3.status_code == 400
    # proceed with departments: captured -> scoping -> in_assessment in one call
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "in_assessment"


@pytest.mark.asyncio
async def test_reject_decision_rejects_change(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    res = await post_meeting(client, admin_auth, change["id"])
    mid = res.json()["id"]
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings/{mid}/decide",
                            json={"decision": "reject"}, headers=admin_auth)
    assert res.status_code == 200
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=admin_auth)
    assert res.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_meeting_authz_pm_or_lead_or_admin(client, admin_auth, seed):
    # engineer is neither admin, lead, nor PM-department member
    change = await create_change(client, admin_auth, seed["project_id"])
    eng_auth = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await post_meeting(client, eng_auth, change["id"])
    assert res.status_code == 400
