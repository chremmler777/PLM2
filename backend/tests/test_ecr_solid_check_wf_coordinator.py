"""Click-through R38 (R5, R18, R24): a revision check workflow step owed by a
department with no real member here is no dead end. The change's
coordinator (the lead who can act, else a Project Management member) acts
for it, sees it in My Tasks, and only who may act gets the buttons
(`can_act` per task). A staffed department keeps its own step."""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.change import ChangeRequest
from tests.conftest import ENGINEER_PASSWORD, login, make_department_member

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def wf(session_factory, seed, part):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.part import PartRevision
    from app.models.workflow import Department, WfStage, WfStep, WfStepRasic, WfTemplate
    from app.services.workflow_service import WorkflowService
    async with session_factory() as s:
        other = User(organization_id=seed["org_id"], username="cw-other",
                     email="cw-other@test.io", full_name="CW other",
                     hashed_password=get_password_hash(ENGINEER_PASSWORD),
                     role="engineer", is_active=True, mfa_enabled=False)
        s.add(other)
        await s.flush()
        other_id = other.id
        dept = Department(name="Memberless Tooling", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        dept_id = dept.id
        tmpl = WfTemplate(name="cw-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        st = WfStage(template_id=tmpl.id, stage_order=1, name="Implement")
        s.add(st)
        await s.flush()
        step = WfStep(stage_id=st.id, step_name="Implement tool change", position_in_stage=1)
        s.add(step)
        await s.flush()
        s.add(WfStepRasic(step_id=step.id, department_id=dept_id, rasic_letter="R"))
        change = ChangeRequest(
            change_number="C-CW-1", title="texture", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["engineer_id"],
            status="in_implementation")
        s.add(change)
        await s.flush()
        rev = await s.get(PartRevision, part["revision_id"])
        rev.originating_change_id = change.id
        await s.commit()
        tmpl_id = tmpl.id
    # the lead and the outsider write (an active department each)
    await make_department_member(session_factory, seed["engineer_id"], "Project Manager")
    await make_department_member(session_factory, other_id, "Development")
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], tmpl_id, seed["engineer_id"])
        await s.commit()
        inst_id = inst.id
    from app.models.workflow import WfInstanceTask
    async with session_factory() as s:
        task_id = (await s.execute(select(WfInstanceTask.id).where(
            WfInstanceTask.instance_id == inst_id,
            WfInstanceTask.status == "active"))).scalar_one()
    return {"inst": inst_id, "task": task_id, "dept": dept_id, "other": other_id}


def _url(wf, tail=""):
    return f"/api/v1/workflow-instances/{wf['inst']}{tail}"


async def test_the_lead_acts_for_a_department_with_no_member(client, eng_auth, wf):
    out = (await client.get(_url(wf), headers=eng_auth)).json()
    task = next(t for t in out["tasks"] if t["id"] == wf["task"])
    assert task["can_act"] is True
    assert "no member here" in task["coordinator_hint"]
    mine = (await client.get("/api/v1/workflow-instances/my-tasks", headers=eng_auth)).json()
    row = next(t for t in mine if t["task_id"] == wf["task"])
    assert row["coordinated"] is True and "no member here" in row["hint"]
    res = await client.post(_url(wf, f"/tasks/{wf['task']}/complete"), headers=eng_auth,
                            json={"decision": "approved"})
    assert res.status_code == 200, res.text


async def test_negative_an_outsider_neither_sees_buttons_nor_acts(client, wf):
    auth = await login(client, "cw-other@test.io", ENGINEER_PASSWORD)
    out = (await client.get(_url(wf), headers=auth)).json()
    assert next(t for t in out["tasks"] if t["id"] == wf["task"])["can_act"] is False
    mine = (await client.get("/api/v1/workflow-instances/my-tasks", headers=auth)).json()
    assert all(t["task_id"] != wf["task"] for t in mine)
    res = await client.post(_url(wf, f"/tasks/{wf['task']}/complete"), headers=auth,
                            json={"decision": "approved"})
    assert res.status_code == 400


async def test_negative_a_staffed_department_keeps_its_step(
        client, eng_auth, wf, session_factory):
    from app.models.workflow import UserDepartment
    async with session_factory() as s:
        s.add(UserDepartment(user_id=wf["other"], department_id=wf["dept"]))
        await s.commit()
    out = (await client.get(_url(wf), headers=eng_auth)).json()
    assert next(t for t in out["tasks"] if t["id"] == wf["task"])["can_act"] is False
    res = await client.post(_url(wf, f"/tasks/{wf['task']}/complete"), headers=eng_auth,
                            json={"decision": "approved"})
    assert res.status_code == 400
    # the member acts
    auth = await login(client, "cw-other@test.io", ENGINEER_PASSWORD)
    res = await client.post(_url(wf, f"/tasks/{wf['task']}/complete"), headers=auth,
                            json={"decision": "approved"})
    assert res.status_code == 200, res.text
