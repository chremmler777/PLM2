"""Retest round 2026-10-27 (fixer C): T2 an internal change's later routing
stages (Summation & Budget, Customer activities) open no PM / Sales task;
T9 one next action; T12 the validation issue's wait text and owner while
APQP confirms limits; F9 customer numbers first; F17 Finance's costing
summation; released -> closed for an internal lead."""
import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.notification import Notification
from app.models.workflow import (
    WfInstance, WfInstanceTask, WfStage, WfStep, WfStepRasic, WfTemplate,
)
from tests.conftest import make_department_member

pytestmark = pytest.mark.asyncio


async def _later_stage_instance(session_factory, seed, *, customer: bool):
    """A change-scoped instance whose stage 1 is answered, in costing, on a
    template carrying Summation & Budget (PM R, Sales A) and Customer
    activities (Sales R, PM A)."""
    dev = await make_department_member(session_factory, seed["engineer_id"], "Development")
    pm = await make_department_member(session_factory, seed["admin_id"], "Project Manager")
    sales = await make_department_member(session_factory, seed["admin_id"], "Sales")
    async with session_factory() as s:
        tmpl = WfTemplate(name=f"t2-{customer}", version=1, is_active=True,
                          created_by=seed["admin_id"])
        s.add(tmpl); await s.flush()
        layout = [(1, "Feasibility & Assessment", [(dev, "R")]),
                  (2, "Summation & Budget", [(pm, "R"), (sales, "A")]),
                  (3, "Customer activities", [(sales, "R"), (pm, "A")])]
        for order, name, deps in layout:
            st = WfStage(template_id=tmpl.id, stage_order=order, name=name)
            s.add(st); await s.flush()
            step = WfStep(stage_id=st.id, step_name=name, position_in_stage=1)
            s.add(step); await s.flush()
            for d, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=d, rasic_letter=letter))
        c = ChangeRequest(change_number=f"C-T2-{customer}", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=customer, status="costing")
        s.add(c); await s.flush()
        inst = WfInstance(template_id=tmpl.id, change_id=c.id, status="active",
                          current_stage_order=1, started_by=seed["engineer_id"])
        s.add(inst); await s.flush()
        s.add(WfInstanceTask(instance_id=inst.id, stage_order=1, department_id=dev,
                             rasic_letter="R", status="approved", is_actionable=True))
        await s.commit()
        return inst.id, c.id, pm, sales


async def test_t2_internal_change_opens_no_summation_tasks(session_factory, seed):
    from app.services.workflow_service import WorkflowService
    iid, cid, pm, sales = await _later_stage_instance(session_factory, seed, customer=False)
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        await WorkflowService._maybe_advance_stage(s, inst)
        await s.commit()
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == iid,
            WfInstanceTask.stage_order > 1))).scalars().all()
        assert tasks and all(t.status == "waived" for t in tasks)
        assert all("internal change" in (t.notes or "") for t in tasks)
        assert inst.status == "completed"
        # nobody is told of a task (or of "all stages approved")
        notes = (await s.execute(select(Notification))).scalars().all()
        assert notes == []


async def test_t2_customer_change_keeps_its_later_stages(session_factory, seed):
    """NEGATIVE: a customer change's summation stays the engine's (unchanged)."""
    from app.services.workflow_service import WorkflowService
    iid, cid, pm, sales = await _later_stage_instance(session_factory, seed, customer=True)
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        await WorkflowService._maybe_advance_stage(s, inst)
        await s.commit()
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        assert inst.status == "active" and inst.current_stage_order == 2
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == iid,
            WfInstanceTask.stage_order == 2))).scalars().all()
        assert {t.status for t in tasks} == {"active"}


async def _approved_change(session_factory, seed, *, planned: bool, validated: bool):
    from datetime import date, datetime
    from app.models.change_cost import ChangeGate
    from app.models.change_plan import ChangePlanTask
    async with session_factory() as s:
        c = ChangeRequest(change_number=f"C-T9-{planned}{validated}", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=False, status="approved",
                          bank_build_mode="running_change" if validated else None,
                          timing_validated_at=datetime.utcnow() if validated else None)
        s.add(c); await s.flush()
        s.add(ChangeGate(change_id=c.id, gate_key="release"))
        if planned:
            s.add(ChangePlanTask(change_id=c.id, plan="detailed", name="Tool",
                                 start_date=date.today(), created_by=seed["admin_id"]))
        await s.commit()
        return c.id


async def _lead_actions(session_factory, seed, cid):
    from app.models.entities import User
    from app.services.change_service import ChangeService
    await make_department_member(session_factory, seed["engineer_id"], "Process Engineer")
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        return await ChangeService.my_actions(s, change, await s.get(User, seed["engineer_id"]))


async def test_t9_approved_change_shows_one_next_step(session_factory, seed):
    """No plan yet: the lead's one step is the plan (with its due), the
    release gate is not offered beside it."""
    cid = await _approved_change(session_factory, seed, planned=False, validated=False)
    acts = await _lead_actions(session_factory, seed, cid)
    kinds = [a["kind"] for a in acts]
    assert "gate" not in kinds
    watch = [a for a in acts if a["kind"] == "plan_watch"]
    assert len(watch) == 1 and watch[0].get("due_date")
    assert "detailed plan" in watch[0]["hint"]


async def test_t9_release_gate_is_the_step_once_the_rest_is_done(session_factory, seed):
    cid = await _approved_change(session_factory, seed, planned=True, validated=True)
    acts = await _lead_actions(session_factory, seed, cid)
    kinds = [a["kind"] for a in acts]
    assert kinds.count("gate") == 1 and "plan_watch" not in kinds
    gate = next(a for a in acts if a["kind"] == "gate")
    assert gate.get("due_date")


from tests.test_ecr_solid_fix_concession import (  # noqa: E402,F401
    REF, _fail_weight, _issue, _iurl, _who, fix,
)
from tests.test_validation_checks import _auth, _url, val  # noqa: E402,F401


async def test_t12_issue_waits_on_apqp_while_the_limits_are_unconfirmed(
        client, fix, session_factory):
    await _fail_weight(client, fix)
    issue = await _issue(client, fix)
    tool = await _auth(client, fix, "Tool Engineer")
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 503.0, "max_value": 509.0,
                        "measuring_ref": REF, "what_changed_kind": "parameter",
                        "what_changed_ref": "holding pressure -5 bar, PS-114 rev C"}})
    assert res.status_code == 201 and res.json()["status"] == "passed", res.text
    issue = await _issue(client, fix)
    assert issue["status"] not in ("closed", "accepted")
    assert issue["check"]["limits_pending"] is True
    assert issue["waiting_on"].startswith("APQP confirms the limits of")
    # the close refusal names APQP, not "answered 'passed' again"
    from app.models.entities import User
    from app.services.change_service import ChangeError, ChangeService
    from app.services.validation_issue_service import ValidationIssueService
    async with session_factory() as s:
        change = await ChangeService.get_change(s, fix["change_id"])
        admin = (await s.execute(select(User).where(User.role == "admin"))).scalars().first()
        with pytest.raises(ChangeError) as e:
            await ValidationIssueService.close(s, change, issue["id"], "x", admin)
        assert "APQP confirms the limits" in str(e.value)
        assert "passed' again" not in str(e.value)
        # the release row's owner is APQP, not Quality
        change.status = "in_validation"
        nxt = await ChangeService.next_step_missing(s, change)
        row = next(i for i in nxt["items"] if i["key"] == "validation_issues")
        assert row["who"].startswith("VI-1: APQP confirms the limits")
