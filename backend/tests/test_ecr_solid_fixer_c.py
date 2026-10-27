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
