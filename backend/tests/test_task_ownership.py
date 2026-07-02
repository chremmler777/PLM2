# backend/tests/test_task_ownership.py
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_ownership_columns_and_overdue_property(session_factory, seed):
    from app.models.workflow import (
        Department, WfTemplate, WfStage, WfStep, WfStepRasic, WfInstanceTask)
    from app.models.change import ChangeAssessment

    async with session_factory() as s:
        dept = Department(name="Own Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        tmpl = WfTemplate(name="own-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        s.add(stage)
        await s.flush()
        step = WfStep(stage_id=stage.id, step_name="do it", position_in_stage=1)
        s.add(step)
        await s.flush()
        s.add(WfStepRasic(step_id=step.id, department_id=dept.id, rasic_letter="R"))
        await s.commit()
        dept_id = dept.id

    async with session_factory() as s:
        task = WfInstanceTask(
            instance_id=None, stage_order=1, step_id=None, department_id=dept_id,
            rasic_letter="R", status="active", is_actionable=True,
            owner_id=seed["engineer_id"],
            accepted_at=datetime.utcnow(),
            due_date=datetime.utcnow() - timedelta(days=1),
        )
        assert task.overdue is True
        task.due_date = datetime.utcnow() + timedelta(days=1)
        assert task.overdue is False
        task.due_date = datetime.utcnow() - timedelta(days=1)
        task.status = "approved"
        assert task.overdue is False

        a = ChangeAssessment(change_id=None, department_id=dept_id,
                             status="active",
                             due_date=datetime.utcnow() - timedelta(hours=2))
        assert a.overdue is True
        assert hasattr(a, "owner_id") and hasattr(a, "accepted_at")


@pytest_asyncio.fixture
async def two_stage_template(session_factory, seed):
    """Two-stage template, one R dept per stage; dept has the engineer as member."""
    from app.models.workflow import (
        Department, UserDepartment, WfTemplate, WfStage, WfStep, WfStepRasic)
    async with session_factory() as s:
        dept = Department(name="Stamp Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        tmpl = WfTemplate(name="stamp-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        for order in (1, 2):
            stage = WfStage(template_id=tmpl.id, stage_order=order, name=f"S{order}")
            s.add(stage)
            await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"step{order}",
                          position_in_stage=1)
            s.add(step)
            await s.flush()
            s.add(WfStepRasic(step_id=step.id, department_id=dept.id,
                              rasic_letter="R"))
            s.add(WfStepRasic(step_id=step.id, department_id=dept.id,
                              rasic_letter="I"))
        await s.commit()
        return {"template_id": tmpl.id, "dept_id": dept.id}


async def test_actionable_tasks_get_default_due_date(
        session_factory, seed, part, two_stage_template):
    from app.models.workflow import WfInstanceTask
    from app.services.workflow_service import WorkflowService, DEFAULT_TASK_DUE_DAYS

    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], two_stage_template["template_id"],
            seed["engineer_id"])
        await s.commit()
        inst_id = inst.id

    async with session_factory() as s:
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst_id))).scalars().all()
        actionable = [t for t in tasks if t.is_actionable]
        noted = [t for t in tasks if not t.is_actionable]
        assert actionable and noted
        for t in actionable:
            assert t.due_date is not None
            delta_days = (t.due_date - datetime.utcnow()).total_seconds() / 86400
            assert DEFAULT_TASK_DUE_DAYS - 1 < delta_days <= DEFAULT_TASK_DUE_DAYS
        assert all(t.due_date is None for t in noted)
