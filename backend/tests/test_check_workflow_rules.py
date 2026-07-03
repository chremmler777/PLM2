# backend/tests/test_check_workflow_rules.py
import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_new_model_columns_exist(session_factory, seed):
    from app.models.workflow import (
        CheckWorkflowStandard, WfTemplate, WfStage, WfStep,
        WF_TASK_DECISIONS, CHECK_WF_ITEM_CATEGORIES,
    )
    from app.models.part import PartRevision

    assert "waived" in WF_TASK_DECISIONS
    assert "tool" in CHECK_WF_ITEM_CATEGORIES

    async with session_factory() as s:
        tmpl = WfTemplate(name="cols-check", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        s.add(stage)
        await s.flush()
        step = WfStep(stage_id=stage.id, step_name="3D", position_in_stage=1)
        s.add(step)
        std = CheckWorkflowStandard(item_category="tool", template_id=tmpl.id)
        s.add(std)
        await s.commit()
        assert step.requires_cad_evidence is False
        assert step.four_eyes is False
        assert std.template_version == 1

    async with session_factory() as s:
        rev = PartRevision(part_id=None, revision_name="X1", phase="ecn",
                           status="draft")
        # column presence check only — no flush needed
        assert rev.no_geometry_change in (False, None)
        assert hasattr(rev, "originating_change_id")
        assert hasattr(rev, "no_geometry_change_by")
        assert hasattr(rev, "no_geometry_change_at")
        assert hasattr(rev, "no_geometry_change_reason")


import pytest_asyncio


@pytest_asyncio.fixture
async def rules_template(session_factory, seed):
    """2-stage template: stage 1 evidence-gated step, stage 2 four-eyes step.
    One department carries R in both stages so the same user could act twice."""
    from app.models.workflow import (
        Department, WfTemplate, WfStage, WfStep, WfStepRasic, UserDepartment)
    async with session_factory() as s:
        dept = Department(name="Rules Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        # The tests drive this dept's tasks as both the engineer and the admin
        # (four-eyes needs two different actors); complete_task's
        # department-membership guard requires the engineer to be a member
        # (the admin is exempt by role).
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        await s.flush()
        tmpl = WfTemplate(name="rules-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        st1 = WfStage(template_id=tmpl.id, stage_order=1, name="Design")
        s.add(st1)
        await s.flush()
        step1 = WfStep(stage_id=st1.id, step_name="Update 3D data",
                       position_in_stage=1, requires_cad_evidence=True)
        s.add(step1)
        await s.flush()
        s.add(WfStepRasic(step_id=step1.id, department_id=dept.id, rasic_letter="R"))
        st2 = WfStage(template_id=tmpl.id, stage_order=2, name="Design check")
        s.add(st2)
        await s.flush()
        step2 = WfStep(stage_id=st2.id, step_name="Design review",
                       position_in_stage=1, four_eyes=True)
        s.add(step2)
        await s.flush()
        s.add(WfStepRasic(step_id=step2.id, department_id=dept.id, rasic_letter="R"))
        await s.commit()
        return {"template_id": tmpl.id, "dept_id": dept.id}


async def _start_instance(session_factory, seed, part, rules_template):
    from app.services.workflow_service import WorkflowService
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], rules_template["template_id"],
            seed["engineer_id"])
        await s.commit()
        return inst.id


async def _active_task_id(session_factory, instance_id, stage_order):
    from app.models.workflow import WfInstanceTask
    async with session_factory() as s:
        return (await s.execute(
            select(WfInstanceTask.id).where(
                WfInstanceTask.instance_id == instance_id,
                WfInstanceTask.stage_order == stage_order,
                WfInstanceTask.status == "active"))).scalars().first()


async def test_waive_requires_notes_and_advances_stage(
        session_factory, seed, part, rules_template):
    from app.services.workflow_service import WorkflowService
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    task_id = await _active_task_id(session_factory, inst_id, 1)

    async with session_factory() as s:
        with pytest.raises(ValueError):
            await WorkflowService.complete_task(s, task_id, "waived", None,
                                                seed["engineer_id"])

    async with session_factory() as s:
        inst = await WorkflowService.complete_task(
            s, task_id, "waived", "document-only change", seed["engineer_id"])
        await s.commit()
        assert inst.current_stage_order == 2


async def test_evidence_gate_blocks_approval_without_evidence(
        session_factory, seed, part, rules_template):
    from app.services.workflow_service import WorkflowService
    from app.models.part import PartRevision
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    task_id = await _active_task_id(session_factory, inst_id, 1)

    async with session_factory() as s:
        with pytest.raises(ValueError, match="evidence"):
            await WorkflowService.complete_task(s, task_id, "approved", None,
                                                seed["engineer_id"])

    async with session_factory() as s:
        rev = await s.get(PartRevision, part["revision_id"])
        rev.no_geometry_change = True
        await s.commit()

    async with session_factory() as s:
        inst = await WorkflowService.complete_task(
            s, task_id, "approved", None, seed["engineer_id"])
        await s.commit()
        assert inst.current_stage_order == 2


async def test_four_eyes_blocks_previous_stage_completer(
        session_factory, seed, part, rules_template):
    from app.services.workflow_service import WorkflowService
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    t1 = await _active_task_id(session_factory, inst_id, 1)
    async with session_factory() as s:
        await WorkflowService.complete_task(s, t1, "waived", "n/a",
                                            seed["engineer_id"])
        await s.commit()
    t2 = await _active_task_id(session_factory, inst_id, 2)

    async with session_factory() as s:
        with pytest.raises(ValueError, match="4-eyes"):
            await WorkflowService.complete_task(s, t2, "approved", None,
                                                seed["engineer_id"])

    async with session_factory() as s:
        inst = await WorkflowService.complete_task(s, t2, "approved", None,
                                                   seed["admin_id"])
        await s.commit()
        assert inst.status == "completed"


async def _stage_actionable(session_factory, instance_id, stage_order):
    """Active, actionable (R/A) tasks of a stage as (task_id, step_name) tuples."""
    from app.models.workflow import WfInstanceTask, WfStep
    async with session_factory() as s:
        return (await s.execute(
            select(WfInstanceTask.id, WfStep.step_name)
            .join(WfStep, WfInstanceTask.step_id == WfStep.id)
            .where(WfInstanceTask.instance_id == instance_id,
                   WfInstanceTask.stage_order == stage_order,
                   WfInstanceTask.is_actionable == True,  # noqa: E712
                   WfInstanceTask.status == "active"))).all()


async def test_seeded_ecn_template_end_to_end(
        session_factory, seed, part, check_wf_standards):
    """Drive the SEEDED 'ECN Implementation (Article)' template end-to-end: evidence
    gate on stage 1, four-eyes block on stage 2, advance to stage 3, then the
    reject-restart recency rule via implementation_progress."""
    from app.services.workflow_service import WorkflowService
    from app.services.change_service import ChangeService
    from app.models.change import ChangeRequest, ChangeImpactedItem
    from app.models.workflow import WfTemplate, WfInstance
    from app.models.part import PartRevision
    from sqlalchemy.orm import selectinload

    from app.models.workflow import Department, UserDepartment

    async with session_factory() as s:
        tmpl = (await s.execute(select(WfTemplate).where(
            WfTemplate.name == "ECN Implementation (Article)"))).scalar_one()
        tmpl_id = tmpl.id
        inst = await WorkflowService.start_workflow(
            s, part["revision_id"], tmpl_id, seed["engineer_id"])
        # Stage 1 ("Design") is all R&D-R; grant the engineer membership
        # so complete_task's department-membership guard doesn't block them.
        rd = (await s.execute(select(Department).where(
            Department.name == "R&D"))).scalar_one()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=rd.id))
        await s.commit()
        inst_id = inst.id

    # --- Stage 1 "Design" ---
    s1 = await _stage_actionable(session_factory, inst_id, 1)
    three_d = [tid for tid, name in s1 if name == "Update 3D data"]
    assert three_d, "expected the evidence-gated 3D step to be actionable"

    # Evidence gate: approving the 3D R-task without evidence is blocked.
    async with session_factory() as s:
        with pytest.raises(ValueError, match="evidence"):
            await WorkflowService.complete_task(
                s, three_d[0], "approved", None, seed["engineer_id"])

    # Sign 'no geometry change' to satisfy the CAD-evidence rule.
    async with session_factory() as s:
        rev = await s.get(PartRevision, part["revision_id"])
        rev.no_geometry_change = True
        await s.commit()

    # Complete every actionable stage-1 task with the engineer.
    for tid, _name in s1:
        async with session_factory() as s:
            await WorkflowService.complete_task(
                s, tid, "approved", None, seed["engineer_id"])
            await s.commit()

    # --- Stage 2 "Design check" (four_eyes) ---
    s2 = await _stage_actionable(session_factory, inst_id, 2)
    assert s2, "expected stage 2 to be active"
    # Engineer completed stage 1 -> four-eyes rule blocks them here.
    async with session_factory() as s:
        with pytest.raises(ValueError, match="4-eyes"):
            await WorkflowService.complete_task(
                s, s2[0][0], "approved", None, seed["engineer_id"])
    # Admin (fresh eyes) completes the stage-2 tasks.
    for tid, _name in s2:
        async with session_factory() as s:
            await WorkflowService.complete_task(
                s, tid, "approved", None, seed["admin_id"])
            await s.commit()

    # Advanced to stage 3.
    async with session_factory() as s:
        inst = await s.get(WfInstance, inst_id)
        assert inst.status == "active"
        assert inst.current_stage_order == 3

    # --- Reject-restart recency rule ---
    s3 = await _stage_actionable(session_factory, inst_id, 3)
    async with session_factory() as s:
        rej = await WorkflowService.complete_task(
            s, s3[0][0], "rejected", "needs rework", seed["admin_id"])
        await s.commit()
        assert rej.status == "rejected"

    # Restart: a fresh instance on the same revision (allowed — old one rejected).
    async with session_factory() as s:
        new_inst = await WorkflowService.start_workflow(
            s, part["revision_id"], tmpl_id, seed["engineer_id"])
        await s.commit()
        new_id = new_inst.id
    assert new_id != inst_id

    # Full-change variant: implementation_progress rolls up the NEWEST instance.
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=seed["project_id"], title="recency",
            change_type="tooling", raised_by=seed["engineer_id"],
            lead_id=seed["engineer_id"])
        s.add(ChangeImpactedItem(
            change_id=change.id, part_id=part["part_id"], is_lead=True,
            resulting_revision_id=part["revision_id"],
            created_by=seed["engineer_id"]))
        await s.commit()
        cid = change.id

    async with session_factory() as s:
        change = (await s.execute(
            select(ChangeRequest).where(ChangeRequest.id == cid)
            .options(selectinload(ChangeRequest.impacted_items)))).scalar_one()
        progress = await ChangeService.implementation_progress(s, change)
        assert progress["items"][0]["instance_id"] == new_id


async def test_wf_events_write_audit_log(session_factory, seed, part, rules_template):
    from app.models.entities import AuditLog
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "wf_instance",
            AuditLog.entity_id == inst_id))).scalars().all()
    assert any(r.action == "wf_started" for r in rows)
