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
        Department, WfTemplate, WfStage, WfStep, WfStepRasic)
    async with session_factory() as s:
        dept = Department(name="Rules Dept", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        tmpl = WfTemplate(name="rules-tpl", version=1, is_active=True,
                          created_by=seed["engineer_id"])
        s.add(tmpl)
        await s.flush()
        st1 = WfStage(template_id=tmpl.id, stage_order=1, name="Konstruktion")
        s.add(st1)
        await s.flush()
        step1 = WfStep(stage_id=st1.id, step_name="3D-Daten aktualisieren",
                       position_in_stage=1, requires_cad_evidence=True)
        s.add(step1)
        await s.flush()
        s.add(WfStepRasic(step_id=step1.id, department_id=dept.id, rasic_letter="R"))
        st2 = WfStage(template_id=tmpl.id, stage_order=2, name="Design-Check")
        s.add(st2)
        await s.flush()
        step2 = WfStep(stage_id=st2.id, step_name="Konstruktionsprüfung",
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


async def test_wf_events_write_audit_log(session_factory, seed, part, rules_template):
    from app.models.entities import AuditLog
    inst_id = await _start_instance(session_factory, seed, part, rules_template)
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "wf_instance",
            AuditLog.entity_id == inst_id))).scalars().all()
    assert any(r.action == "wf_started" for r in rows)
