"""Internal costing branch: PM approves the summation total, no quote step."""
import pytest
from sqlalchemy import update

from tests.conftest import login, ENGINEER_PASSWORD, advance_to_assessment
from tests.test_change_scoping import create_change, add_item_and_lead


async def to_costing(session_factory, change_id):
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change_id).values(status="costing"))
        await s.commit()


@pytest.mark.asyncio
async def test_internal_approval_snapshots_amount_and_unblocks_approved(
        client, admin_auth, seed, part, session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    await to_costing(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={"note": "budget ok"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["internal_approved_by"] == seed["admin_id"]
    assert body["internal_approved_amount"] is not None  # summation snapshot (0.0 with no cost lines)
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_internal_approval_guards(client, admin_auth, seed, part,
                                        session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    # wrong status
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={}, headers=admin_auth)
    assert res.status_code == 400
    # customer-relevant change refuses internal approval
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"customer_relevant": True}, headers=admin_auth)
    await to_costing(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={}, headers=admin_auth)
    assert res.status_code == 400
    # non-PM engineer refused on an internal change (not admin, not PM member)
    change2 = await create_change(client, admin_auth, seed["project_id"],
                                  lead_id=seed["admin_id"])
    await to_costing(session_factory, change2["id"])
    eng_auth = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await client.post(f"/api/v1/changes/{change2['id']}/internal-approval",
                            json={}, headers=eng_auth)
    assert res.status_code == 403

    # even the change lead is refused if they aren't a PM member or admin —
    # the pragmatic PM-gated rule drops the old bare-lead bypass.
    change3 = await create_change(client, admin_auth, seed["project_id"],
                                  lead_id=seed["engineer_id"])
    await to_costing(session_factory, change3["id"])
    res = await client.post(f"/api/v1/changes/{change3['id']}/internal-approval",
                            json={}, headers=eng_auth)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_internal_approval_allows_pm_department_member(
        client, admin_auth, seed, part, session_factory):
    """A Project Manager department member (not admin, not the lead) may
    approve internal costs — no second-signer restriction."""
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        dept = Department(name="Project Manager", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        await s.commit()
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await to_costing(session_factory, change["id"])
    eng_auth = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={"note": "pm approved"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["internal_approved_by"] == seed["engineer_id"]
