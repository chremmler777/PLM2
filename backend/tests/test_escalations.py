# backend/tests/test_escalations.py
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from tests.test_assessment_ownership import _routed_change

pytestmark = pytest.mark.asyncio


async def test_my_tasks_are_owner_aware(client, eng_auth, seed, session_factory,
                                        part):
    from app.models.workflow import (
        Department, UserDepartment, WfTemplate, WfStage, WfStep, WfStepRasic,
        WfInstanceTask)
    from app.services.workflow_service import WorkflowService

    async with session_factory() as s:
        dept = Department(name="MT Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        tmpl = WfTemplate(name="mt-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        s.add(stage)
        await s.flush()
        for i in (1, 2):
            step = WfStep(stage_id=stage.id, step_name=f"s{i}", position_in_stage=i)
            s.add(step)
            await s.flush()
            s.add(WfStepRasic(step_id=step.id, department_id=dept.id,
                              rasic_letter="R"))
        await s.commit()
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], tmpl.id, seed["engineer_id"])
        await s.commit()
        inst_id = inst.id

    # own one of the two tasks and make it overdue
    async with session_factory() as s:
        task_ids = [t for (t,) in await s.execute(
            select(WfInstanceTask.id).where(
                WfInstanceTask.instance_id == inst_id,
                WfInstanceTask.is_actionable == True))]  # noqa: E712
        await s.execute(update(WfInstanceTask).where(WfInstanceTask.id == task_ids[0])
                        .values(owner_id=seed["engineer_id"],
                                accepted_at=datetime.utcnow(),
                                due_date=datetime.utcnow() - timedelta(days=2)))
        await s.commit()

    res = await client.get("/api/v1/workflow-instances/my-tasks", headers=eng_auth)
    assert res.status_code == 200, res.text
    tasks = [t for t in res.json() if t["instance_id"] == inst_id]
    assert len(tasks) == 2
    first, second = tasks[0], tasks[1]
    assert first["mine"] is True and first["overdue"] is True
    assert first["owner_name"]
    assert second["mine"] is False and second["owner_id"] is None


async def test_change_my_tasks_owner_fields(client, eng_auth, seed,
                                            session_factory, part):
    from app.models.workflow import Department, UserDepartment
    from app.models.change import ChangeAssessment
    async with session_factory() as s:
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            s.add(Department(name=n, flow_type="action", is_active=True))
        await s.commit()
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.status == "active"))).scalars().first()
        s.add(UserDepartment(user_id=seed["engineer_id"],
                             department_id=a.department_id))
        a.owner_id = seed["engineer_id"]
        a.due_date = datetime.utcnow() - timedelta(hours=1)
        await s.commit()

    res = await client.get("/api/v1/changes/my-tasks", headers=eng_auth)
    assert res.status_code == 200, res.text
    mine = [t for t in res.json() if t["change_id"] == change["id"]]
    assert mine and mine[0]["mine"] is True and mine[0]["overdue"] is True
    assert mine[0]["due_date"] is not None


async def test_lead_escalations_roll_up(client, eng_auth, seed, session_factory,
                                        part, check_wf_standards):
    """Engineer leads a change with an overdue assessment AND an overdue check-WF
    task -> both appear in /changes/my-escalations, worst first."""
    from app.models.change import ChangeAssessment, ChangeRequest
    from app.models.change_cost import ChangeGate
    from app.models.workflow import WfInstanceTask, WfInstance
    from app.models.part import PartRevision
    from app.models.workflow import Department
    from app.services.change_service import ChangeService

    async with session_factory() as s:
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            s.add(Department(name=n, flow_type="action", is_active=True))
        await s.commit()
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])

    # overdue assessment (5 days)
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.status == "active"))).scalars().first()
        a.due_date = datetime.utcnow() - timedelta(days=5)
        # drive the change to in_implementation directly to spawn the check WF
        c = await s.get(ChangeRequest, change["id"])
        c.status = "approved"
        await s.execute(update(ChangeGate).where(ChangeGate.change_id == c.id)
                        .values(decision="yes"))
        await s.commit()

    async with session_factory() as s:
        c = await ChangeService.get_change(s, change["id"])
        await ChangeService.transition(s, c, "in_implementation",
                                       seed["engineer_id"])
        await s.commit()

    # make one spawned WF task overdue (2 days)
    async with session_factory() as s:
        rev_id = (await s.execute(select(PartRevision.id).where(
            PartRevision.originating_change_id == change["id"]))).scalars().first()
        task_id = (await s.execute(
            select(WfInstanceTask.id)
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .where(WfInstance.part_revision_id == rev_id,
                   WfInstanceTask.status == "active",
                   WfInstanceTask.is_actionable == True)  # noqa: E712
        )).scalars().first()
        await s.execute(update(WfInstanceTask).where(WfInstanceTask.id == task_id)
                        .values(due_date=datetime.utcnow() - timedelta(days=2)))
        await s.commit()

    res = await client.get("/api/v1/changes/my-escalations", headers=eng_auth)
    assert res.status_code == 200, res.text
    rows = res.json()
    kinds = [r["kind"] for r in rows]
    assert "assessment" in kinds and "wf_task" in kinds
    assert rows[0]["days_overdue"] >= rows[-1]["days_overdue"]
    assert rows[0]["days_overdue"] == 5
    assert all(r["change_number"] == change["change_number"] for r in rows
               if r["change_id"] == change["id"])


async def test_escalations_empty_for_non_lead(client, admin_auth):
    res = await client.get("/api/v1/changes/my-escalations", headers=admin_auth)
    assert res.status_code == 200
    assert res.json() == []
