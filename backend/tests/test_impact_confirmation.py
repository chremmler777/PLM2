# backend/tests/test_impact_confirmation.py
"""Task 18: Engineering (R&D) owns the affected-items decision. The lead
proposes impacted items (existing flow, unchanged); an R&D department member
confirms the set; kickoff (approved -> in_implementation) is soft-guarded on
that confirmation, bypassable only via an approved transition deviation."""
import pytest
import pytest_asyncio
from datetime import datetime
from sqlalchemy import select, update

from tests.test_changes import departments  # noqa: F401 (reused fixture)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def rd_member_auth(client, session_factory, seed):
    """A user who is a member of the 'R&D' department (not the change lead)."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment

    async with session_factory() as s:
        dept = Department(name="R&D", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        user = User(
            organization_id=seed["org_id"], username="rdmember", email="rd@test.io",
            full_name="RD Member", hashed_password=get_password_hash("rd-secret-12"),
            role="engineer", is_active=True, mfa_enabled=False,
        )
        s.add(user)
        await s.flush()
        s.add(UserDepartment(user_id=user.id, department_id=dept.id))
        await s.commit()
        user_id = user.id
        dept_id = dept.id

    login = await client.post("/api/v1/auth/login",
                              json={"email": "rd@test.io", "password": "rd-secret-12"})
    assert login.status_code == 200, login.text
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return {"auth": auth, "user_id": user_id, "dept_id": dept_id}


async def _create_change_with_impacted_item(client, eng_auth, seed, part):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "impact confirm",
        "change_type": "physical_part", "lead_id": seed["engineer_id"],
    }, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    added = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                              json={"part_id": part["part_id"], "is_lead": True},
                              headers=eng_auth)
    assert added.status_code in (200, 201), added.text
    return cid


async def test_confirm_as_rd_member_sets_fields_and_changelog(
        client, eng_auth, rd_member_auth, seed, part):
    cid = await _create_change_with_impacted_item(client, eng_auth, seed, part)

    res = await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                            headers=rd_member_auth["auth"])
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["impact_confirmed_by"] == rd_member_auth["user_id"]
    assert data["impact_confirmed_by_name"] == "RD Member"
    assert data["impact_confirmed_at"] is not None

    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=eng_auth)).json()
    assert any(e["action"] == "impact_confirmed" for e in log)


async def test_confirm_as_non_member_403(client, eng_auth, seed, part):
    """The lead (engineer) is not in R&D and is not admin -> 403."""
    cid = await _create_change_with_impacted_item(client, eng_auth, seed, part)
    res = await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=eng_auth)
    assert res.status_code == 403, res.text


async def test_confirm_as_admin_allowed(client, eng_auth, admin_auth, seed, part):
    cid = await _create_change_with_impacted_item(client, eng_auth, seed, part)
    res = await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_confirm_with_zero_impacted_items_409(
        client, eng_auth, rd_member_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "no items",
        "change_type": "physical_part", "lead_id": seed["engineer_id"],
    }, headers=eng_auth)
    cid = res.json()["id"]
    confirm = await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                                headers=rd_member_auth["auth"])
    assert confirm.status_code == 409, confirm.text


async def test_confirm_response_includes_deadline_state(
        client, eng_auth, rd_member_auth, seed, part):
    """The confirm endpoint returns a ChangeResponse; deadline_state must be
    populated (like the GET endpoints do) rather than left as None/absent."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "impact confirm deadline",
        "change_type": "physical_part", "lead_id": seed["engineer_id"],
    }, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    added = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                              json={"part_id": part["part_id"], "is_lead": True},
                              headers=eng_auth)
    assert added.status_code in (200, 201), added.text
    patched = await client.patch(f"/api/v1/changes/{cid}",
                                 json={"required_by_date": "2020-01-01T00:00:00"},
                                 headers=eng_auth)
    assert patched.status_code == 200, patched.text

    confirm = await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                                headers=rd_member_auth["auth"])
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["deadline_state"] == "overdue"


async def test_confirm_is_idempotent(client, eng_auth, rd_member_auth, seed, part):
    """Re-confirming (e.g. a second R&D reviewer) refreshes who/when instead
    of erroring - the set may legitimately be re-reviewed unchanged."""
    cid = await _create_change_with_impacted_item(client, eng_auth, seed, part)
    first = await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                              headers=rd_member_auth["auth"])
    assert first.status_code == 200, first.text
    second = await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                               headers=rd_member_auth["auth"])
    assert second.status_code == 200, second.text


async def _approved_change_for_kickoff(session_factory, seed, part_id, *, confirm=False,
                                       confirmed_by=None):
    from app.services.change_service import ChangeService
    from app.models.change import ChangeImpactedItem
    from app.models.change_cost import ChangeGate
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=seed["project_id"], title="kickoff-impact",
            change_type="tooling", raised_by=seed["engineer_id"],
            lead_id=seed["engineer_id"])
        s.add(ChangeImpactedItem(change_id=change.id, part_id=part_id,
                                 is_lead=True, created_by=seed["engineer_id"]))
        change.status = "approved"
        if confirm:
            change.impact_confirmed_by = confirmed_by or seed["engineer_id"]
            change.impact_confirmed_at = datetime.utcnow()
        await s.execute(update(ChangeGate).where(ChangeGate.change_id == change.id)
                        .values(decision="yes"))
        await s.commit()
        return change.id


async def test_kickoff_blocked_without_confirmation(session_factory, seed, part):
    from app.services.change_service import ChangeService, ChangeError

    cid = await _approved_change_for_kickoff(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        with pytest.raises(ChangeError, match="impact_not_confirmed"):
            await ChangeService.transition(s, change, "in_implementation",
                                           seed["engineer_id"])


async def test_kickoff_proceeds_after_confirmation(
        session_factory, seed, part, check_wf_standards):
    from app.services.change_service import ChangeService
    from app.models.change import ChangeImpactedItem

    cid = await _approved_change_for_kickoff(session_factory, seed, part["part_id"],
                                             confirm=True)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_implementation",
                                       seed["engineer_id"])
        await s.commit()

    async with session_factory() as s:
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        assert item.resulting_revision_id is not None


async def _approved_change_via_api(client, eng_auth, admin_auth, seed, departments,
                                   session_factory):
    """Drive a real change all the way to 'approved' through the HTTP API
    (reuses test_changes.py's flow helper) so the impact_not_confirmed guard
    and its deviation bypass are exercised through the actual endpoint."""
    from tests.test_changes import _advance_to_quoted, _transition

    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth,
                                      session_factory)
    cid = change["id"]
    await client.post(f"/api/v1/changes/{cid}/customer-response",
                      json={"response": "accepted"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"}, headers=admin_auth)
    res = await _transition(client, eng_auth, cid, "approved")
    assert res.status_code == 200, res.text
    return cid


async def test_kickoff_blocked_via_api_with_reason(
        client, eng_auth, admin_auth, seed, departments, check_wf_standards,
        session_factory):
    cid = await _approved_change_via_api(client, eng_auth, admin_auth, seed, departments,
                                         session_factory)
    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_implementation"}, headers=eng_auth)
    assert blocked.status_code == 400
    assert "impact_not_confirmed" in blocked.json()["detail"]


async def test_deviation_bypasses_impact_confirmation_guard(
        client, eng_auth, admin_auth, seed, departments, check_wf_standards,
        session_factory):
    cid = await _approved_change_via_api(client, eng_auth, admin_auth, seed, departments,
                                         session_factory)
    dev = (await client.post(f"/api/v1/changes/{cid}/deviations", json={
        "to_status": "in_implementation", "reason": "kickoff before R&D signs off"},
        headers=eng_auth)).json()
    ok = await client.post(
        f"/api/v1/changes/{cid}/deviations/{dev['id']}/decide",
        json={"decision": "approved"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text

    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_implementation"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "in_implementation"


async def test_add_impacted_item_after_confirmation_clears_it(
        client, eng_auth, rd_member_auth, seed, part):
    cid = await _create_change_with_impacted_item(client, eng_auth, seed, part)
    confirm = await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                                headers=rd_member_auth["auth"])
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["impact_confirmed_at"] is not None

    part2 = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "IC-2", "name": "second",
        "part_type": "internal_mfg", "data_classification": "confidential",
    }, headers=eng_auth)
    assert part2.status_code in (200, 201), part2.text
    added = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                              json={"part_id": part2.json()["id"]}, headers=eng_auth)
    assert added.status_code in (200, 201), added.text

    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert res.json()["impact_confirmed_at"] is None
    assert res.json()["impact_confirmed_by"] is None

    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=eng_auth)).json()
    assert any(e["action"] == "impact_confirmation_reset" for e in log)


async def test_remove_impacted_item_after_confirmation_clears_it(
        client, eng_auth, rd_member_auth, seed, part):
    cid = await _create_change_with_impacted_item(client, eng_auth, seed, part)
    # add a second, removable (non-lead) item before confirming
    part2 = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "IC-3", "name": "removable",
        "part_type": "internal_mfg", "data_classification": "confidential",
    }, headers=eng_auth)
    item2 = (await client.post(f"/api/v1/changes/{cid}/impacted-items",
                               json={"part_id": part2.json()["id"]},
                               headers=eng_auth)).json()

    confirm = await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                                headers=rd_member_auth["auth"])
    assert confirm.status_code == 200, confirm.text

    removed = await client.delete(
        f"/api/v1/changes/{cid}/impacted-items/{item2['id']}", headers=eng_auth)
    assert removed.status_code in (200, 204), removed.text

    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert res.json()["impact_confirmed_at"] is None

    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=eng_auth)).json()
    assert any(e["action"] == "impact_confirmation_reset" for e in log)
