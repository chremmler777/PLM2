# backend/tests/test_check_workflow_rules.py
import pytest

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
