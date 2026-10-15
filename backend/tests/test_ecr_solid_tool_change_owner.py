"""ECR-solid C21 (spec §8-9): the Tool Engineer owns the tool change and the
trial, Process the parameter sheets; 'Tool sampled' is asked of the Tool
Engineer only; Toolshop has its typical positions; a soft guard into
validation names every tool whose "Implement tool change" is still open."""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.services import validation_checklist

pytestmark = pytest.mark.asyncio


def test_tool_sampled_is_the_tool_engineers_alone():
    assert "sampled" in validation_checklist.keys_for("Tool Engineer")
    for dept in ("Manufacturing Engineer", "Process Engineer"):
        keys = validation_checklist.keys_for(dept)
        assert "sampled" not in keys and "measured" in keys
    # an older row still reads by name
    assert validation_checklist.label_for("sampled", "Process Engineer") == "Tool sampled"


def test_toolshop_has_typical_positions():
    from app.services import costing_tags
    keys = [k for k, *_ in costing_tags.DEPARTMENT_CATEGORIES["Toolshop"]]
    assert "toolmaker_hours" in keys


async def _tool_change_world(session_factory, seed, *, done: bool, stage: int = 3):
    """An in_implementation change whose tool revision has a check workflow
    with its 'Implement tool change' task open (or done)."""
    from app.models.change import ChangeImpactedItem, ChangeRequest
    from app.models.part import Part, PartRevision
    from app.models.workflow import (
        WfInstance, WfInstanceTask, WfStage, WfStep, WfTemplate)
    from app.services.wf_seed_service import seed_check_standards
    async with session_factory() as s:
        await seed_check_standards(s)
        tool = Part(project_id=seed["project_id"], part_number="T-3454", name="Tool",
                    part_type="internal_mfg", item_category="tool",
                    created_by=seed["admin_id"])
        s.add(tool)
        await s.flush()
        rev = PartRevision(part_id=tool.id, revision_name="E1", phase="review",
                           status="draft", created_by=seed["admin_id"])
        s.add(rev)
        await s.flush()
        change = ChangeRequest(
            change_number="C-TC-1", title="tool change", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"],
            status="in_implementation", customer_relevant=False)
        s.add(change)
        await s.flush()
        s.add(ChangeImpactedItem(change_id=change.id, part_id=tool.id, is_lead=True,
                                 resulting_revision_id=rev.id, created_by=seed["admin_id"]))
        tmpl = (await s.execute(select(WfTemplate).where(
            WfTemplate.name == "ECN Implementation (Tool)"))).scalars().first()
        step = (await s.execute(
            select(WfStep).join(WfStage, WfStage.id == WfStep.stage_id).where(
                WfStage.template_id == tmpl.id,
                WfStep.step_name == "Implement tool change"))).scalar_one()
        inst = WfInstance(template_id=tmpl.id, part_revision_id=rev.id, status="active",
                          current_stage_order=stage, started_by=seed["admin_id"])
        s.add(inst)
        await s.flush()
        from app.models.workflow import Department
        te = (await s.execute(select(Department).where(
            Department.name == "Tool Engineer"))).scalar_one()
        if stage >= 3:      # tasks are created stage by stage
            s.add(WfInstanceTask(instance_id=inst.id, stage_order=3, step_id=step.id,
                                 department_id=te.id, rasic_letter="R",
                                 status="approved" if done else "active",
                                 is_actionable=True,
                                 completed_at=datetime.utcnow() if done else None))
        await s.commit()
        return change.id


async def test_open_tool_change_holds_validation_softly(session_factory, seed):
    from app.models.change import ChangeRequest
    from app.services.change_service import ChangeService
    cid = await _tool_change_world(session_factory, seed, done=False)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        assert await ChangeService.open_tool_changes(s, change) == ["T-3454"]
        reasons = await ChangeService._guard_reasons(s, change, "in_validation")
        rules = {getattr(r, "key", None) for r in reasons}
        assert "tool_change_open" in rules
        assert any("T-3454" in str(r) for r in reasons)


async def test_done_tool_change_does_not_hold(session_factory, seed):
    from app.services.change_service import ChangeService
    cid = await _tool_change_world(session_factory, seed, done=True)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        assert await ChangeService.open_tool_changes(s, change) == []


async def test_tool_change_not_reached_yet_holds_too(session_factory, seed):
    """Review L5 loop 2: the check workflow is still in design (stage 1),
    so the 'Implement tool change' task does not exist yet: the tool change
    is plainly not done and the guard names the tool."""
    from app.services.change_service import ChangeService
    cid = await _tool_change_world(session_factory, seed, done=False, stage=1)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        assert await ChangeService.open_tool_changes(s, change) == ["T-3454"]
