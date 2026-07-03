"""Task 1: change-scoped WfInstance + assessment->task link (read-through)."""
import pytest
from datetime import datetime, timedelta
from app.models.workflow import WfInstance, WfInstanceTask, WfTemplate, Department
from app.models.change import ChangeRequest, ChangeAssessment


async def _mk_template(session):
    t = WfTemplate(name="ECM Bewertung Test", created_by=1)
    session.add(t)
    await session.flush()
    return t


@pytest.mark.asyncio
async def test_instance_can_be_change_scoped(session_factory, seed):
    async with session_factory() as session:
        t = await _mk_template(session)
        chg = ChangeRequest(change_number="C-E-001", title="x", reason="y",
                            change_type="physical_part",
                            project_id=seed["project_id"],
                            raised_by=seed["admin_id"])
        session.add(chg)
        await session.flush()
        inst = WfInstance(template_id=t.id, change_id=chg.id, part_revision_id=None,
                          status="active", current_stage_order=1,
                          started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        assert inst.change_id == chg.id and inst.part_revision_id is None


@pytest.mark.asyncio
async def test_assessment_links_to_task_and_reads_through(session_factory, seed):
    async with session_factory() as session:
        t = await _mk_template(session)
        chg = ChangeRequest(change_number="C-E-002", title="x", reason="y",
                            change_type="physical_part",
                            project_id=seed["project_id"],
                            raised_by=seed["admin_id"])
        dept = Department(name="R&D-E", flow_type="change")
        session.add_all([chg, dept])
        await session.flush()
        inst = WfInstance(template_id=t.id, change_id=chg.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        task = WfInstanceTask(instance_id=inst.id, stage_order=1, step_id=None,
                              department_id=dept.id, rasic_letter="R",
                              status="approved", is_actionable=True,
                              owner_id=seed["admin_id"],
                              due_date=datetime.utcnow() + timedelta(days=7))
        session.add(task)
        await session.flush()
        a = ChangeAssessment(change_id=chg.id, department_id=dept.id,
                             stage_order=1, rasic_letter="R", status="pending",
                             wf_instance_task_id=task.id)
        session.add(a)
        await session.flush()
        await session.refresh(a)
        # R/A execution state reads through from the task
        assert a.effective_status == "submitted"        # approved -> submitted
        assert a.effective_owner_id == seed["admin_id"]
        assert a.effective_due_date == task.due_date


@pytest.mark.asyncio
async def test_sc_assessment_derives_status_without_task_write(session_factory, seed):
    async with session_factory() as session:
        chg = ChangeRequest(change_number="C-E-003", title="x", reason="y",
                            change_type="physical_part",
                            project_id=seed["project_id"],
                            raised_by=seed["admin_id"])
        dept = Department(name="Log-E", flow_type="change")
        session.add_all([chg, dept])
        await session.flush()
        a = ChangeAssessment(change_id=chg.id, department_id=dept.id,
                             stage_order=2, rasic_letter="S", status="pending")
        session.add(a)
        await session.flush()
        await session.refresh(a)
        assert a.effective_status == "pending"          # no task yet -> own column
        a.submitted_at = datetime.utcnow()
        assert a.effective_status == "submitted"        # payload submitted
