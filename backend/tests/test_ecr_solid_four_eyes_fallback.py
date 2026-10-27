"""F1 (test 2026-10-26, P0), DECIDED BY CLAUDE (Christoph confirms): a 4-eyes
Design review whose department has no second active member (prod:
Development = Christoph alone) is no dead end. The project's Tool Engineer
responsible (else its backup, else the change lead) reviews, never the one
who did Design; the history says so, and the review is in the fallback
reviewer's My Tasks with the change number."""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.change import ChangeChangelog, ChangeRequest
from tests.conftest import ENGINEER_PASSWORD, login, make_department_member

pytestmark = pytest.mark.asyncio


async def _user(s, seed, name):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    u = User(organization_id=seed["org_id"], username=name, email=f"{name}@test.io",
             full_name=name.replace(".", " ").title(),
             hashed_password=get_password_hash(ENGINEER_PASSWORD),
             role="engineer", is_active=True, mfa_enabled=False)
    s.add(u)
    await s.flush()
    return u.id


@pytest_asyncio.fixture
async def fe(session_factory, seed, part):
    from app.models.part import PartRevision
    from app.models.workflow import (
        ProjectResponsible, WfStage, WfStep, WfStepRasic, WfTemplate)
    from app.services.workflow_service import WorkflowService
    async with session_factory() as s:
        dale = await _user(s, seed, "dale.te")
        backup = await _user(s, seed, "te.backup")
        lead = await _user(s, seed, "pm.lead")
        await s.commit()
    dev = await make_department_member(session_factory, seed["engineer_id"], "Development")
    te = await make_department_member(session_factory, dale, "Tool Engineer")
    await make_department_member(session_factory, backup, "Tool Engineer")
    await make_department_member(session_factory, lead, "Project Manager")
    async with session_factory() as s:
        tmpl = WfTemplate(name="fe-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        st1 = WfStage(template_id=tmpl.id, stage_order=1, name="Design")
        st2 = WfStage(template_id=tmpl.id, stage_order=2, name="Design check")
        st3 = WfStage(template_id=tmpl.id, stage_order=3, name="Industrialization")
        s.add_all([st1, st2, st3])
        await s.flush()
        s1 = WfStep(stage_id=st1.id, step_name="Update 3D data", position_in_stage=1)
        s2 = WfStep(stage_id=st2.id, step_name="Design review", position_in_stage=1,
                    four_eyes=True)
        s3 = WfStep(stage_id=st3.id, step_name="Implement tool change", position_in_stage=1)
        s.add_all([s1, s2, s3])
        await s.flush()
        s.add_all([WfStepRasic(step_id=s1.id, department_id=dev, rasic_letter="R"),
                   WfStepRasic(step_id=s2.id, department_id=dev, rasic_letter="R"),
                   WfStepRasic(step_id=s3.id, department_id=te, rasic_letter="R")])
        change = ChangeRequest(
            change_number="C-FE-1", title="grain", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=lead, status="in_implementation")
        s.add(change)
        await s.flush()
        s.add(ProjectResponsible(project_id=seed["project_id"], department_id=te,
                                 user_id=dale, backup_user_id=backup))
        rev = await s.get(PartRevision, part["revision_id"])
        rev.originating_change_id = change.id
        await s.commit()
        tmpl_id, change_id = tmpl.id, change.id
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], tmpl_id, seed["engineer_id"])
        await s.commit()
        inst_id = inst.id
    return {"inst": inst_id, "change": change_id, "dale": dale, "backup": backup,
            "lead": lead, "dev": dev, "te": te}


async def _open(session_factory, inst, stage):
    from app.models.workflow import WfInstanceTask
    async with session_factory() as s:
        return (await s.execute(select(WfInstanceTask.id).where(
            WfInstanceTask.instance_id == inst, WfInstanceTask.stage_order == stage,
            WfInstanceTask.status == "active"))).scalar_one()


async def _design_done(client, fe, session_factory):
    """The only Development member (the engineer, as Christoph) does Design."""
    eng = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    t1 = await _open(session_factory, fe["inst"], 1)
    res = await client.post(f"/api/v1/workflow-instances/{fe['inst']}/tasks/{t1}/complete",
                            headers=eng, json={"decision": "approved"})
    assert res.status_code == 200, res.text
    return eng


async def test_tool_engineer_reviews_when_development_has_one_member(
        client, fe, session_factory):
    eng = await _design_done(client, fe, session_factory)
    t2 = await _open(session_factory, fe["inst"], 2)
    # the designer cannot review his own design
    res = await client.post(f"/api/v1/workflow-instances/{fe['inst']}/tasks/{t2}/complete",
                            headers=eng, json={"decision": "approved"})
    assert res.status_code == 400 and "4-eyes" in res.text
    dale = await login(client, "dale.te@test.io", ENGINEER_PASSWORD)
    mine = (await client.get("/api/v1/workflow-instances/my-tasks", headers=dale)).json()
    row = next(r for r in mine if r["task_id"] == t2)
    assert row["change_number"] == "C-FE-1" and "4-eyes fallback" in row["hint"]
    out = (await client.get(f"/api/v1/workflow-instances/{fe['inst']}", headers=dale)).json()
    assert next(t for t in out["tasks"] if t["id"] == t2)["can_act"] is True
    res = await client.post(f"/api/v1/workflow-instances/{fe['inst']}/tasks/{t2}/complete",
                            headers=dale, json={"decision": "approved"})
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        lines = (await s.execute(select(ChangeChangelog.action_description).where(
            ChangeChangelog.change_id == fe["change"],
            ChangeChangelog.action == "four_eyes_fallback"))).scalars().all()
    assert lines == ["4-eyes fallback: Dale Te reviews, Development has no second member"]
    # the workflow reaches "Implement tool change"
    t3 = await _open(session_factory, fe["inst"], 3)
    assert t3 is not None


async def test_negative_backup_and_lead_cannot_while_responsible_is_live(
        client, fe, session_factory):
    await _design_done(client, fe, session_factory)
    t2 = await _open(session_factory, fe["inst"], 2)
    for who in ("te.backup@test.io", "pm.lead@test.io"):
        auth = await login(client, who, ENGINEER_PASSWORD)
        res = await client.post(
            f"/api/v1/workflow-instances/{fe['inst']}/tasks/{t2}/complete",
            headers=auth, json={"decision": "approved"})
        assert res.status_code == 400, who


async def test_backup_then_lead_when_tool_engineer_did_design_or_is_gone(
        client, fe, session_factory, seed):
    from app.models.entities import User
    from app.services.workflow_service import WorkflowService
    from app.models.workflow import WfInstanceTask
    await _design_done(client, fe, session_factory)
    t2 = await _open(session_factory, fe["inst"], 2)
    async with session_factory() as s:
        (await s.get(User, fe["dale"])).is_active = False
        await s.commit()
    async with session_factory() as s:
        fb = await WorkflowService.four_eyes_fallback(s, await s.get(WfInstanceTask, t2))
        assert fb["user_id"] == fe["backup"]
        (await s.get(User, fe["backup"])).is_active = False
        await s.commit()
    async with session_factory() as s:
        fb = await WorkflowService.four_eyes_fallback(s, await s.get(WfInstanceTask, t2))
        assert fb["user_id"] == fe["lead"]


async def test_negative_no_fallback_when_development_has_a_second_member(
        client, fe, session_factory, seed):
    from app.services.workflow_service import WorkflowService
    from app.models.workflow import WfInstanceTask
    await _design_done(client, fe, session_factory)
    async with session_factory() as s:
        second = await _user(s, seed, "dev.two")
        await s.commit()
    await make_department_member(session_factory, second, "Development")
    t2 = await _open(session_factory, fe["inst"], 2)
    async with session_factory() as s:
        assert await WorkflowService.four_eyes_fallback(
            s, await s.get(WfInstanceTask, t2)) is None
    dale = await login(client, "dale.te@test.io", ENGINEER_PASSWORD)
    res = await client.post(f"/api/v1/workflow-instances/{fe['inst']}/tasks/{t2}/complete",
                            headers=dale, json={"decision": "approved"})
    assert res.status_code == 400


async def test_f4_the_tool_change_task_tells_its_owner_with_the_change(
        client, fe, session_factory):
    """F4: the stage's task notice names the step and the change, once."""
    from app.models.notification import Notification
    await _design_done(client, fe, session_factory)
    t2 = await _open(session_factory, fe["inst"], 2)
    dale = await login(client, "dale.te@test.io", ENGINEER_PASSWORD)
    res = await client.post(f"/api/v1/workflow-instances/{fe['inst']}/tasks/{t2}/complete",
                            headers=dale, json={"decision": "approved"})
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        rows = (await s.execute(select(Notification).where(
            Notification.user_id == fe["dale"], Notification.kind == "task_new"))).scalars().all()
    # N3: Dale was told of the review he does as the fallback, then of the tool change
    assert [r.title for r in rows] == ["Your task: Design review (C-FE-1)",
                                       "Your task: Implement tool change (C-FE-1)"]
    assert "due" in rows[1].body and "grain" in rows[1].body


async def test_n3_the_review_notice_goes_to_the_fallback_reviewer(
        client, fe, session_factory, seed):
    """Retest-s1 N3: the Design review notice reaches Dale (the fallback
    reviewer), not the designer the 4-eyes rule refuses."""
    from app.models.notification import Notification
    await _design_done(client, fe, session_factory)
    async with session_factory() as s:
        told = [(n.user_id, n.title) for n in (await s.execute(select(Notification).where(
            Notification.kind == "task_new"))).scalars()
                if "Design review" in (n.title or "")]
    assert [u for u, _ in told] == [fe["dale"]], told
