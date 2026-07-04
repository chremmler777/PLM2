"""Department membership admin (Task 17): GET/PUT /v1/users/{id}/departments,
dev-seed idempotence, and the complete_task department-membership guard."""
import pytest_asyncio
import pytest
from sqlalchemy import select

from app.models.workflow import Department, UserDepartment
from tests.conftest import approve_gates, advance_to_assessment

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def two_depts(session_factory):
    async with session_factory() as s:
        d1 = Department(name="Dept One", flow_type="action", is_active=True, sort_order=1)
        d2 = Department(name="Dept Two", flow_type="action", is_active=True, sort_order=2)
        s.add_all([d1, d2])
        await s.commit()
        return {"d1": d1.id, "d2": d2.id}


async def test_non_admin_forbidden_from_put(client, eng_auth, seed, two_depts):
    res = await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [two_depts["d1"]]}, headers=eng_auth,
    )
    assert res.status_code == 403


async def test_get_returns_current_memberships(client, admin_auth, seed, two_depts):
    res = await client.get(f"/api/v1/users/{seed['engineer_id']}/departments", headers=admin_auth)
    assert res.status_code == 200
    assert res.json() == []

    await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [two_depts["d1"]]}, headers=admin_auth,
    )
    res = await client.get(f"/api/v1/users/{seed['engineer_id']}/departments", headers=admin_auth)
    assert [d["id"] for d in res.json()] == [two_depts["d1"]]


async def test_put_replaces_set(client, admin_auth, seed, two_depts):
    res = await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [two_depts["d1"], two_depts["d2"]]}, headers=admin_auth,
    )
    assert res.status_code == 200
    assert len(res.json()) == 2

    res = await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [two_depts["d1"]]}, headers=admin_auth,
    )
    assert res.status_code == 200
    ids = [d["id"] for d in res.json()]
    assert ids == [two_depts["d1"]]


async def test_put_audits_departments_set(client, admin_auth, seed, two_depts, session_factory):
    from app.models.entities import AuditLog

    await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [two_depts["d1"]]}, headers=admin_auth,
    )
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "user",
            AuditLog.entity_id == seed["engineer_id"],
            AuditLog.action == "departments_set"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == seed["admin_id"]


async def test_put_rejects_unknown_department_ids(client, admin_auth, seed):
    res = await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [999999]}, headers=admin_auth,
    )
    assert res.status_code == 400


async def test_seed_dev_department_memberships_is_idempotent(session_factory):
    from app.auth.security import get_password_hash
    from app.models.entities import Organization, User
    from app.services.wf_seed_service import seed_dev_department_memberships

    async with session_factory() as s:
        org = Organization(name="O", code="o", is_active=True)
        s.add(org)
        await s.flush()
        rd = Department(name="R&D", flow_type="action", is_active=True)
        other = Department(name="Other Dept", flow_type="action", is_active=True)
        s.add_all([rd, other])
        await s.flush()
        test_user = User(
            organization_id=org.id, username="testuser", email="test@example.com",
            full_name="Test User", hashed_password=get_password_hash("password"),
            role="engineer", is_active=True, mfa_enabled=False)
        admin_user = User(
            organization_id=org.id, username="admin", email="admin@example.com",
            full_name="Administrator", hashed_password=get_password_hash("admin1234"),
            role="admin", is_active=True, mfa_enabled=False)
        s.add_all([test_user, admin_user])
        await s.commit()
        test_id, admin_id, rd_id, other_id = test_user.id, admin_user.id, rd.id, other.id

    async with session_factory() as s:
        await seed_dev_department_memberships(s)
        await s.commit()

    async with session_factory() as s:
        test_depts = {d for (d,) in (await s.execute(
            select(UserDepartment.department_id).where(
                UserDepartment.user_id == test_id))).all()}
        admin_depts = {d for (d,) in (await s.execute(
            select(UserDepartment.department_id).where(
                UserDepartment.user_id == admin_id))).all()}
    assert test_depts == {rd_id}
    assert admin_depts == {rd_id, other_id}

    # Run again -> idempotent, no duplicate rows (would violate the composite PK).
    async with session_factory() as s:
        await seed_dev_department_memberships(s)
        await s.commit()

    async with session_factory() as s:
        test_depts2 = {d for (d,) in (await s.execute(
            select(UserDepartment.department_id).where(
                UserDepartment.user_id == test_id))).all()}
        admin_depts2 = {d for (d,) in (await s.execute(
            select(UserDepartment.department_id).where(
                UserDepartment.user_id == admin_id))).all()}
    assert test_depts2 == {rd_id}
    assert admin_depts2 == {rd_id, other_id}


# --- complete_task enforcement -------------------------------------------

@pytest_asyncio.fixture
async def guard_template(session_factory, seed):
    """One-stage, one-dept template: 'Guard Dept' R, for exercising
    complete_task's membership guard directly."""
    from app.models.workflow import WfTemplate, WfStage, WfStep, WfStepRasic
    async with session_factory() as s:
        dept = Department(name="Guard Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        tmpl = WfTemplate(name="guard-tpl", version=1, is_active=True,
                          created_by=seed["admin_id"])
        s.add(tmpl)
        await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        s.add(stage)
        await s.flush()
        step = WfStep(stage_id=stage.id, step_name="Step", position_in_stage=1)
        s.add(step)
        await s.flush()
        s.add(WfStepRasic(step_id=step.id, department_id=dept.id, rasic_letter="R"))
        await s.commit()
        return {"template_id": tmpl.id, "dept_id": dept.id}


@pytest_asyncio.fixture
async def guard_part(client, eng_auth, seed):
    res = await client.post(
        "/api/v1/parts",
        json={"project_id": seed["project_id"], "part_number": "GD-1", "name": "Guard Part",
              "part_type": "sub_assembly", "data_classification": "confidential"},
        headers=eng_auth,
    )
    assert res.status_code in (200, 201), res.text
    part_id = res.json()["id"]
    res = await client.post(
        f"/api/v1/parts/{part_id}/revisions/rfq", json={"summary": "initial"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    return {"part_id": part_id, "revision_id": res.json()["id"]}


async def _start_and_task(client, eng_auth, guard_part, guard_template):
    res = await client.post(
        f"/api/v1/workflow-instances/revisions/{guard_part['revision_id']}/start",
        json={"template_id": guard_template["template_id"]}, headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    inst = res.json()
    task = next(t for t in inst["tasks"] if t["department_id"] == guard_template["dept_id"])
    return inst["id"], task["id"]


async def test_complete_task_blocked_for_non_member(
        client, eng_auth, guard_part, guard_template):
    inst_id, task_id = await _start_and_task(client, eng_auth, guard_part, guard_template)
    res = await client.post(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/complete",
        json={"decision": "approved"}, headers=eng_auth,
    )
    assert res.status_code == 400, res.text
    assert "department" in res.json()["detail"].lower()


async def test_complete_task_ok_for_member(
        client, eng_auth, admin_auth, guard_part, guard_template, seed):
    await client.put(
        f"/api/v1/users/{seed['engineer_id']}/departments",
        json={"department_ids": [guard_template["dept_id"]]}, headers=admin_auth,
    )
    inst_id, task_id = await _start_and_task(client, eng_auth, guard_part, guard_template)
    res = await client.post(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/complete",
        json={"decision": "approved"}, headers=eng_auth,
    )
    assert res.status_code == 200, res.text


async def test_complete_task_admin_exempt(
        client, eng_auth, admin_auth, guard_part, guard_template):
    inst_id, task_id = await _start_and_task(client, eng_auth, guard_part, guard_template)
    res = await client.post(
        f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/complete",
        json={"decision": "approved"}, headers=admin_auth,
    )
    assert res.status_code == 200, res.text


async def test_submit_assessment_blocked_for_non_member(
        client, eng_auth, admin_auth, seed, session_factory):
    """submit_assessment delegates blocking (R/A) submissions to complete_task,
    so its membership guard applies through that path too."""
    from app.models.change import ChangeRequest, ChangeRoutingStandard
    from app.models.workflow import WfTemplate, WfStage, WfStep, WfStepRasic

    async with session_factory() as s:
        dept = Department(name="Submit Guard Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        tmpl = WfTemplate(name="submit-guard-tpl", version=1, is_active=True,
                          created_by=seed["admin_id"])
        s.add(tmpl)
        await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        s.add(stage)
        await s.flush()
        step = WfStep(stage_id=stage.id, step_name="Step", position_in_stage=1)
        s.add(step)
        await s.flush()
        s.add(WfStepRasic(step_id=step.id, department_id=dept.id, rasic_letter="R"))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=tmpl.id,
                                    template_version=1, updated_by=seed["admin_id"]))
        await s.commit()
        dept_id = dept.id

    body = {"project_id": seed["project_id"], "title": "sg", "change_type": "physical_part",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=eng_auth)).json()
    await approve_gates(client, eng_auth, c["id"])
    p = (await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "SG-1", "name": "SG-1",
        "part_type": "internal_mfg", "item_category": "article"}, headers=eng_auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items",
                      json={"part_id": p["id"]}, headers=eng_auth)
    await advance_to_assessment(client, eng_auth, session_factory, c["id"])

    res = await client.post(
        f"/api/v1/changes/{c['id']}/assessments",
        json={"department_id": dept_id, "verdict": "feasible"}, headers=eng_auth,
    )
    assert res.status_code == 400, res.text

    await client.put(f"/api/v1/users/{seed['engineer_id']}/departments",
                     json={"department_ids": [dept_id]}, headers=admin_auth)
    res = await client.post(
        f"/api/v1/changes/{c['id']}/assessments",
        json={"department_id": dept_id, "verdict": "feasible"}, headers=eng_auth,
    )
    assert res.status_code == 200, res.text
