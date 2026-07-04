# backend/tests/test_my_actions.py
"""Task 19: GET /changes/{id}/my-actions — the cockpit's 'Your actions'
panel. Each action kind mirrors the authz of the endpoint that actually
performs it (see ChangeService.my_actions for the mirrored source)."""
import pytest
import pytest_asyncio

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

    login = await client.post("/api/v1/auth/login",
                              json={"email": "rd@test.io", "password": "rd-secret-12"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_engineer_with_owned_active_task_gets_assessment_action(
        client, eng_auth, seed, session_factory):
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import Department

    async with session_factory() as s:
        dept = Department(name="QA-MA", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        chg = ChangeRequest(change_number="C-MA-001", title="x", reason="y",
                            change_type="physical_part", project_id=seed["project_id"],
                            raised_by=seed["admin_id"])
        s.add(chg)
        await s.flush()
        a = ChangeAssessment(change_id=chg.id, department_id=dept.id, stage_order=1,
                             rasic_letter="S", status="active", verdict="pending",
                             owner_id=seed["engineer_id"])
        s.add(a)
        await s.commit()
        cid = chg.id

    res = await client.get(f"/api/v1/changes/{cid}/my-actions", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    kinds = [act["kind"] for act in body["actions"]]
    assert "assessment" in kinds
    assessment_actions = [a for a in body["actions"] if a["kind"] == "assessment"]
    assert assessment_actions[0]["target_tab"] == "assessments"
    assert assessment_actions[0]["assessment_id"] == a.id


async def test_lead_with_pending_deviation_gets_deviation_decision(
        client, eng_auth, admin_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "dev", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    dev = await client.post(f"/api/v1/changes/{cid}/deviations", json={
        "to_status": "in_assessment", "reason": "need it now"}, headers=admin_auth)
    assert dev.status_code == 200, dev.text

    out = await client.get(f"/api/v1/changes/{cid}/my-actions", headers=eng_auth)
    assert out.status_code == 200, out.text
    kinds = [a["kind"] for a in out.json()["actions"]]
    assert "deviation_decision" in kinds


async def test_rd_member_on_unconfirmed_approved_change_gets_impact_confirm(
        client, eng_auth, rd_member_auth, seed, part, session_factory):
    from app.models.change import ChangeRequest

    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "impact", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    added = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                              json={"part_id": part["part_id"], "is_lead": True},
                              headers=eng_auth)
    assert added.status_code in (200, 201), added.text

    async with session_factory() as s:
        chg = await s.get(ChangeRequest, cid)
        chg.status = "approved"
        await s.commit()

    out = await client.get(f"/api/v1/changes/{cid}/my-actions", headers=rd_member_auth)
    assert out.status_code == 200, out.text
    kinds = [a["kind"] for a in out.json()["actions"]]
    assert "impact_confirm" in kinds


async def test_user_with_nothing_gets_empty_list(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "solo", "change_type": "physical_part",
    }, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]

    out = await client.get(f"/api/v1/changes/{cid}/my-actions", headers=eng_auth)
    assert out.status_code == 200, out.text
    assert out.json()["actions"] == []


async def test_admin_sees_gate_action_on_soft_blocked_change(
        client, eng_auth, admin_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "gate", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]

    out = await client.get(f"/api/v1/changes/{cid}/my-actions", headers=admin_auth)
    assert out.status_code == 200, out.text
    body = out.json()
    kinds = [a["kind"] for a in body["actions"]]
    assert "gate" in kinds
    gate_actions = [a for a in body["actions"] if a["kind"] == "gate"]
    assert gate_actions[0]["target_tab"] == "d1"


async def test_response_carries_memberships(client, eng_auth, seed, session_factory):
    from app.models.change import ChangeRequest
    from app.models.workflow import Department, UserDepartment

    async with session_factory() as s:
        dept = Department(name="Membership-Test", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        chg = ChangeRequest(change_number="C-MEM-001", title="x", reason="y",
                            change_type="physical_part", project_id=seed["project_id"],
                            raised_by=seed["admin_id"])
        s.add(chg)
        await s.commit()
        cid = chg.id
        dept_id = dept.id

    out = await client.get(f"/api/v1/changes/{cid}/my-actions", headers=eng_auth)
    assert out.status_code == 200, out.text
    assert dept_id in out.json()["memberships"]
