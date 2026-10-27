"""Tester 2 (2026-10-26) backend findings: T5 a hub admin's real
Development membership signs 'no geometry change'; T6 the rejection letter
is the Sales contact's; T11 an internal change's lead completes Project
Management's check workflow steps; T13 an internal change is not asked
'Customer informed' / PPAP; T15/T17/T19 hand-over, urgent and end notices
reach the involved people once, open cancel votes close with the change."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.change import ChangeConcern, ChangeRequest
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from tests.conftest import ENGINEER_PASSWORD, login, make_department_member

pytestmark = pytest.mark.asyncio


async def _user(s, seed, name, *, role="engineer", hub=False):
    from app.auth.security import get_password_hash
    u = User(organization_id=seed["org_id"], username=name, email=f"{name}@test.io",
             full_name=name.title(), role=role, is_active=True, mfa_enabled=False,
             hashed_password="!" if hub else get_password_hash(ENGINEER_PASSWORD))
    s.add(u)
    await s.flush()
    return u.id


async def test_t5_hub_admin_real_membership_counts(session_factory, seed):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        hub = await _user(s, seed, "christoph", role="admin", hub=True)
        await s.commit()
    await make_department_member(session_factory, hub, "Development")
    await make_department_member(session_factory, seed["admin_id"], "Development")
    async with session_factory() as s:
        assert await ChangeService.real_member_of(
            s, await s.get(User, hub), "Development") is True
        # NEGATIVE: a local admin account's blanket rows stay blind
        assert await ChangeService.real_member_of(
            s, await s.get(User, seed["admin_id"]), "Development") is False


async def test_t6_rejection_rows_name_the_sales_contact(session_factory, seed):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        karl = await _user(s, seed, "karl")
        c = ChangeRequest(change_number="C-T6", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["engineer_id"],
                          sales_owner_id=karl, customer_relevant=True, status="rejected")
        s.add(c)
        await s.commit()
        change = await ChangeService.get_change(s, c.id)
        items = [{"key": "rejection_letter"}, {"key": "rejection_sent"}]
        await ChangeService._default_owners(s, change, items)
    assert [i["who"] for i in items] == ["Sales: Karl", "Sales: Karl"]


async def test_t11_internal_lead_completes_the_pm_step(session_factory, seed, part):
    from app.models.part import PartRevision
    from app.models.workflow import WfStage, WfStep, WfStepRasic, WfTemplate, WfInstanceTask
    from app.services.workflow_service import WorkflowService
    pm = await make_department_member(session_factory, seed["admin_id"], "Project Manager")
    async with session_factory() as s:
        russ = await _user(s, seed, "russ")
        tmpl = WfTemplate(name="t11", version=1, is_active=True, created_by=seed["admin_id"])
        s.add(tmpl); await s.flush()
        st = WfStage(template_id=tmpl.id, stage_order=1, name="Industrialization")
        s.add(st); await s.flush()
        step = WfStep(stage_id=st.id, step_name="Implement tool change", position_in_stage=1)
        s.add(step); await s.flush()
        s.add(WfStepRasic(step_id=step.id, department_id=pm, rasic_letter="A"))
        c = ChangeRequest(change_number="C-T11", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=russ, lead_id=russ, customer_relevant=False,
                          status="in_implementation")
        s.add(c); await s.flush()
        (await s.get(PartRevision, part["revision_id"])).originating_change_id = c.id
        await s.commit()
        tmpl_id, cid = tmpl.id, c.id
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(s, part["revision_id"], tmpl_id,
                                                    seed["admin_id"])
        await s.commit()
        tid = (await s.execute(select(WfInstanceTask.id).where(
            WfInstanceTask.instance_id == inst.id))).scalar_one()
    async with session_factory() as s:
        rows = await WorkflowService.get_four_eyes_fallback_tasks(s, await s.get(User, russ))
        assert [r["task_id"] for r in rows] == [tid]
        await WorkflowService.complete_task(s, tid, "approved", None, russ)
        await s.commit()
    # NEGATIVE: on a customer change the lead is no PM stand-in
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.customer_relevant = True
        await s.commit()
        t = await s.get(WfInstanceTask, tid)
        assert await WorkflowService.internal_lead_acts(s, t, await s.get(User, russ)) is False


def test_t13_internal_change_is_not_asked_customer_rows():
    from app.services import release_checklist as rc
    internal = SimpleNamespace(status="in_validation", customer_relevant=False,
                               released_at=None, closed_at=None)
    customer = SimpleNamespace(status="in_validation", customer_relevant=True,
                               released_at=None, closed_at=None)
    assert "customer_informed" not in rc.keys_for(internal)
    assert "customer_approval" not in rc.keys_for(internal)
    assert {"customer_informed", "customer_approval"} <= set(rc.keys_for(customer))
    # an answer already given stays
    assert "customer_informed" in rc.keys_for(internal, {"customer_informed"})


async def test_t17_t19_handover_and_cancel_tell_the_people_once(session_factory, seed):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        karl = await _user(s, seed, "karl")
        lead = await _user(s, seed, "cody")
        c = ChangeRequest(change_number="C-T19", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=lead,
                          sales_owner_id=karl, customer_relevant=True, status="scoping")
        s.add(c); await s.flush()
        s.add(ChangeConcern(change_id=c.id, kind="reject_proposal", note="drop it",
                            raised_by=karl))
        await s.commit()
        cid = c.id
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.notify_handover_and_end(s, change, "captured", "scoping",
                                                    seed["admin_id"])
        change.cancellation_reason = "Customer dropped the part"
        await ChangeService.notify_handover_and_end(s, change, "scoping", "cancelled",
                                                    seed["admin_id"])
        await s.commit()
        rows = (await s.execute(select(Notification.user_id, Notification.kind))).all()
        vote = (await s.execute(select(ChangeConcern).where(
            ChangeConcern.change_id == cid))).scalar_one()
    assert sorted(r for r in rows if r[1] == "task_new") == sorted(
        [(lead, "task_new"), (karl, "task_new")])
    ended = sorted(u for u, k in rows if k == "change_ended")
    assert ended == sorted([lead, karl, seed["engineer_id"]])
    assert vote.is_open is False


async def test_t18_no_tool_change_answer_makes_the_step_not_applicable(session_factory, seed):
    import json
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    from app.services.change_service import ChangeService
    from app.services.workflow_service import WorkflowService
    from tests.test_ecr_solid_tool_change_owner import _tool_change_world
    from datetime import datetime
    cid = await _tool_change_world(session_factory, seed, done=False)
    te = await make_department_member(session_factory, seed["engineer_id"], "Tool Engineer")
    async with session_factory() as s:
        a = ChangeAssessment(change_id=cid, department_id=te, status="active",
                             rasic_letter="R", details=json.dumps({"impacted": False}))
        s.add(a); await s.commit()
        inst = (await s.execute(select(WfInstance))).scalars().first()
        # NEGATIVE: not answered yet -> still asked
        assert await WorkflowService.no_tool_change_note(s, inst) is None
        a.submitted_at = datetime.utcnow()
        await s.commit()
        assert "no tool change" in await WorkflowService.no_tool_change_note(s, inst)
        # a waived step is no open tool change
        t = (await s.execute(select(WfInstanceTask))).scalars().first()
        t.status = "waived"
        await s.commit()
        change = await ChangeService.get_change(s, cid)
        assert await ChangeService.open_tool_changes(s, change) == []
        # NEGATIVE: an answer that the tool changes keeps the step
        a.details = json.dumps({"impacts": [{"impacted": True, "what": "insert"}]})
        await s.commit()
        assert await WorkflowService.no_tool_change_note(s, inst) is None


async def test_t10_r_and_a_of_one_department_answer_once(session_factory, seed, part):
    from app.models.workflow import WfInstanceTask, WfStage, WfStep, WfStepRasic, WfTemplate
    from app.services.workflow_service import WorkflowService
    dev = await make_department_member(session_factory, seed["engineer_id"], "Development")
    async with session_factory() as s:
        tmpl = WfTemplate(name="t10", version=1, is_active=True, created_by=seed["admin_id"])
        s.add(tmpl); await s.flush()
        st = WfStage(template_id=tmpl.id, stage_order=1, name="Design")
        st2 = WfStage(template_id=tmpl.id, stage_order=2, name="Next")
        s.add_all([st, st2]); await s.flush()
        step = WfStep(stage_id=st.id, step_name="Update 3D data", position_in_stage=1)
        step2 = WfStep(stage_id=st2.id, step_name="Later", position_in_stage=1)
        s.add_all([step, step2]); await s.flush()
        s.add_all([WfStepRasic(step_id=step.id, department_id=dev, rasic_letter="R"),
                   WfStepRasic(step_id=step.id, department_id=dev, rasic_letter="A"),
                   WfStepRasic(step_id=step2.id, department_id=dev, rasic_letter="R")])
        await s.commit()
        tmpl_id = tmpl.id
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(s, part["revision_id"], tmpl_id,
                                                    seed["engineer_id"])
        await s.commit()
        r = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id, WfInstanceTask.rasic_letter == "R",
            WfInstanceTask.stage_order == 1))).scalar_one()
        inst = await WorkflowService.complete_task(s, r.id, "approved", None,
                                                   seed["engineer_id"])
        await s.commit()
        assert inst.current_stage_order == 2
