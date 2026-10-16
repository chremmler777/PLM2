"""Internal costing branch: PM approves the summation total, no quote step."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from tests.conftest import login, ENGINEER_PASSWORD, advance_to_assessment, make_department_member
from tests.test_change_scoping import create_change, add_item_and_lead

# Internal approval is where the release ("released-by") deadline is born.
_RELEASE_DUE = (datetime.utcnow() + timedelta(days=120)).isoformat()


async def to_costing(session_factory, change_id, raised_by=2):
    """Into costing. HARD #8: the raiser never approves; these tests approve
    as the admin or a PM member, so the seeded engineer (id 2) raised it."""
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change_id).values(status="costing", raised_by=raised_by))
        await s.commit()



@pytest.fixture(autouse=True)
async def _admin_in_pm(session_factory, seed):
    """HARD #8 fallback (close-out A1-06): with no configured approver, a
    real Project Manager member approves, no admin shortcut. The admin who
    approves in these tests is one."""
    from tests.conftest import make_department_member
    await make_department_member(session_factory, seed["admin_id"], "Project Manager")


@pytest.fixture
async def pm_auth(client, session_factory, seed, _admin_in_pm):
    """The admin acting as Project Management: an admin's own department
    rows do not approve internal spend (R25), acting puts PM on the record."""
    from tests.conftest import login as _login
    pm = await make_department_member(session_factory, seed["admin_id"], "Project Manager")
    return {**await _login(client, "admin@test.io"), "X-Acts-As-Department": str(pm)}


@pytest.mark.asyncio
async def test_internal_approval_snapshots_amount_and_unblocks_approved(pm_auth,
        client, admin_auth, seed, part, session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await advance_to_assessment(client, admin_auth, session_factory, change["id"])
    await to_costing(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={"note": "budget ok", "release_due_date": _RELEASE_DUE, "rationale": "quality"}, headers=pm_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["internal_approved_by"] == seed["admin_id"]
    assert body["internal_approved_amount"] is not None  # summation snapshot (0.0 with no cost lines)
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "approved"}, headers=admin_auth)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_internal_approval_guards(pm_auth, client, admin_auth, seed, part,
                                        session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    async with session_factory() as s:  # HARD #8: the admin is not the raiser
        from app.models.change import ChangeRequest
        await s.execute(update(ChangeRequest).where(
            ChangeRequest.id == change["id"]).values(raised_by=seed["engineer_id"]))
        await s.commit()
    # wrong status
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={}, headers=pm_auth)
    assert res.status_code == 400
    # customer-relevant change refuses internal approval
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"customer_relevant": True}, headers=admin_auth)
    await to_costing(session_factory, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={}, headers=pm_auth)
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
    from tests.conftest import make_department_member
    await make_department_member(session_factory, seed["engineer_id"], "Project Manager")
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await to_costing(session_factory, change["id"], raised_by=seed["admin_id"])
    eng_auth = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await client.post(f"/api/v1/changes/{change['id']}/internal-approval",
                            json={"note": "pm approved", "release_due_date": _RELEASE_DUE, "rationale": "quality"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["internal_approved_by"] == seed["engineer_id"]


@pytest.mark.asyncio
async def test_internal_approval_requires_release_deadline(pm_auth,
        client, admin_auth, seed, part, session_factory):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 lead_id=seed["admin_id"])
    await add_item_and_lead(client, admin_auth, change["id"], part["part_id"])
    await to_costing(session_factory, change["id"])
    cid = change["id"]
    res = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                            json={"note": "ok"}, headers=pm_auth)
    assert res.status_code == 400
    assert "release deadline" in res.json()["detail"].lower()

    due = (datetime.utcnow() + timedelta(days=30)).isoformat()
    res = await client.post(f"/api/v1/changes/{cid}/internal-approval", json={
        "note": "ok", "release_due_date": due, "release_due_reason": "plant window",
        "rationale": "quality",
    }, headers=pm_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["internal_approved_at"] is not None
    assert body["release_due_date"] is not None
    assert body["release_due_reason"] == "plant window"
    assert body["active_deadline"] == "release"
