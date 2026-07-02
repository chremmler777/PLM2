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
