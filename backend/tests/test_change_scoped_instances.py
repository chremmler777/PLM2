"""Task 1: change-scoped WfInstance + assessment->task link (read-through).
Task 2: change-aware workflow engine (start_change_workflow, gate skips)."""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import select
from app.models.workflow import (
    WfInstance, WfInstanceTask, WfTemplate, Department, UserDepartment,
)
from app.models.change import ChangeRequest, ChangeAssessment
from app.services.workflow_service import WorkflowService
from app.services.wf_seed_service import seed_change_workflows


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


async def _ecm_template(session) -> WfTemplate:
    await seed_change_workflows(session)   # seeds "ECM Bewertung" + departments
    return (await session.execute(select(WfTemplate).where(
        WfTemplate.name == "ECM Bewertung"))).scalar_one()


async def _mk_change(session, seed, number: str) -> ChangeRequest:
    chg = ChangeRequest(change_number=number, title="x", reason="y",
                        change_type="physical_part",
                        project_id=seed["project_id"],
                        raised_by=seed["admin_id"])
    session.add(chg)
    await session.flush()
    return chg


@pytest.mark.asyncio
async def test_start_change_workflow_creates_stage1_tasks(session_factory, seed):
    async with session_factory() as session:
        tmpl = await _ecm_template(session)
        chg = await _mk_change(session, seed, "C-E-010")
        inst = await WorkflowService.start_change_workflow(
            session, chg.id, tmpl.id, seed["admin_id"])
        assert inst.change_id == chg.id and inst.part_revision_id is None
        assert inst.status == "active" and inst.current_stage_order == 1
        tasks = (await session.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id))).scalars().all()
        assert any(t.stage_order == 1 for t in tasks)
        # Idempotent: a second start returns the same active instance.
        again = await WorkflowService.start_change_workflow(
            session, chg.id, tmpl.id, seed["admin_id"])
        assert again.id == inst.id


@pytest.mark.asyncio
async def test_change_scoped_instance_skips_cad_evidence_gate(session_factory, seed):
    # Completing a stage-1 R task on a change-scoped instance must not raise the
    # 3D-evidence error (that rule applies to ECN revisions only) — and must not
    # blow up in _audit on a null part_revision_id.
    async with session_factory() as session:
        tmpl = await _ecm_template(session)
        chg = await _mk_change(session, seed, "C-E-011")
        inst = await WorkflowService.start_change_workflow(
            session, chg.id, tmpl.id, seed["admin_id"])
        task = (await session.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.stage_order == 1,
            WfInstanceTask.is_actionable == True,  # noqa: E712
            WfInstanceTask.rasic_letter == "R",
        ).limit(1))).scalars().first()
        assert task is not None
        # Grant the acting user membership in the task's department (honest
        # fixture: complete_task's 4-eyes guard is satisfied — stage 1 has no
        # prior stage — and the user legitimately belongs to the department).
        session.add(UserDepartment(user_id=seed["admin_id"],
                                   department_id=task.department_id))
        await session.flush()
        result = await WorkflowService.complete_task(
            session, task.id, "approved", "ok", seed["admin_id"])
        await session.refresh(task)
        assert task.status == "approved"
        assert result.status == "active"   # other stage-1 R tasks still open
