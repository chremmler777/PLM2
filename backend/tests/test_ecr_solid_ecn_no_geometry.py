"""ECN check workflow for a revision signed 'no geometry change' (DECIDED BY
CHRISTOPH 2026-10-19, switch RELEASE_V2): the Design and Design check stages
drop, and the steps the release checklist and validation already ask
(inspection plan / PPAP, master data and logistics, sampling / trial, final
release) are not asked twice: the release checklist is the one place. They
are recorded as waived with the reason; the tool change and the process
sheets stay. A workflow already running is shortened when the revision is
signed; its done tasks stay as they are."""
import pytest
from sqlalchemy import select

from app.services import cm_switches

pytestmark = pytest.mark.asyncio

KEPT = {"Implement tool change", "Adjust process / parameter sheets"}


async def _template_id(session_factory, name="ECN Implementation (Article)"):
    from app.models.workflow import WfTemplate
    from app.services.wf_seed_service import seed_check_standards
    async with session_factory() as s:
        await seed_check_standards(s)
        await s.commit()
        return (await s.execute(select(WfTemplate.id).where(
            WfTemplate.name == name))).scalars().first()


async def _sign(session_factory, revision_id, user_id):
    from datetime import datetime
    from app.models.part import PartRevision
    async with session_factory() as s:
        rev = await s.get(PartRevision, revision_id)
        rev.no_geometry_change = True
        rev.no_geometry_change_by = user_id
        rev.no_geometry_change_at = datetime.utcnow()
        rev.no_geometry_change_reason = "texture only"
        await s.commit()


async def _start(session_factory, revision_id, template_id, user_id):
    from app.services.workflow_service import WorkflowService
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(s, revision_id, template_id, user_id)
        await s.commit()
        return inst.id


async def _tasks(session_factory, inst_id):
    from app.models.workflow import WfInstance, WfInstanceTask, WfStep
    async with session_factory() as s:
        inst = await s.get(WfInstance, inst_id)
        rows = (await s.execute(
            select(WfInstanceTask, WfStep.step_name)
            .outerjoin(WfStep, WfStep.id == WfInstanceTask.step_id)
            .where(WfInstanceTask.instance_id == inst_id)
            .order_by(WfInstanceTask.id))).all()
        return inst.status, inst.current_stage_order, [
            (name, t.stage_order, t.rasic_letter, t.status, t.notes) for t, name in rows]


async def test_a_signed_revision_starts_at_industrialization(
        session_factory, seed, part):
    tid = await _template_id(session_factory)
    await _sign(session_factory, part["revision_id"], seed["engineer_id"])
    inst_id = await _start(session_factory, part["revision_id"], tid, seed["admin_id"])
    status, stage, tasks = await _tasks(session_factory, inst_id)
    assert status == "active" and stage == 3
    active = {n for n, _, letter, st, _ in tasks if st == "active"}
    assert active == KEPT
    waived = [(n, o, notes) for n, o, letter, st, notes in tasks if st == "waived"]
    names = {n for n, _, _ in waived}
    assert {"Update 3D data", "Update drawings & documentation", "Design review",
            "Clarify inspection plan / PPAP need",
            "Update master data & logistics"} <= names
    assert all("no geometry change" in notes for _, _, notes in waived)
    # the waived inspection-plan step says where it is asked instead
    plan = next(notes for n, _, notes in waived
                if n == "Clarify inspection plan / PPAP need")
    assert "release checklist" in plan
    # nothing of the dropped steps is noted for C/S/I either
    assert not [t for t in tasks if t[0] not in KEPT and t[3] == "noted"]


async def test_the_shortened_workflow_completes_without_ready_to_go_steps(
        session_factory, seed, part):
    from app.models.workflow import WfInstanceTask
    from app.services.workflow_service import WorkflowService
    tid = await _template_id(session_factory)
    await _sign(session_factory, part["revision_id"], seed["engineer_id"])
    inst_id = await _start(session_factory, part["revision_id"], tid, seed["admin_id"])
    async with session_factory() as s:
        ids = (await s.execute(select(WfInstanceTask.id).where(
            WfInstanceTask.instance_id == inst_id,
            WfInstanceTask.status == "active"))).scalars().all()
    for task_id in ids:
        async with session_factory() as s:
            await WorkflowService.complete_task(s, task_id, "approved", "done",
                                                seed["admin_id"])
            await s.commit()
    status, stage, tasks = await _tasks(session_factory, inst_id)
    assert status == "completed"
    ready = [(n, st) for n, o, _, st, _ in tasks if o == 4]
    assert ready and all(st in ("waived",) for _, st in ready), ready


async def test_signing_a_running_workflow_shortens_it(
        client, eng_auth, session_factory, seed, part):
    tid = await _template_id(session_factory)
    inst_id = await _start(session_factory, part["revision_id"], tid, seed["admin_id"])
    status, stage, _ = await _tasks(session_factory, inst_id)
    assert stage == 1
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "texture only"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    status, stage, tasks = await _tasks(session_factory, inst_id)
    assert status == "active" and stage == 3
    assert {n for n, _, _, st, _ in tasks if st == "active"} == KEPT
    from app.models.workflow import WfInstanceTask
    async with session_factory() as s:
        design = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst_id,
            WfInstanceTask.stage_order == 1,
            WfInstanceTask.is_actionable.is_(True)))).scalars().all()
        assert design and all(t.status == "waived" and t.completed_by == seed["engineer_id"]
                              for t in design)


async def test_unsigned_or_switch_off_or_other_template_keeps_every_stage(
        session_factory, seed, part, monkeypatch):
    """Negative: no signature, the full workflow; RELEASE_V2 off, the full
    workflow even when signed; another template with a 'Design' stage is no
    ECN check workflow and is not touched."""
    from app.models.workflow import (
        Department, WfStage, WfStep, WfStepRasic, WfTemplate)
    tid = await _template_id(session_factory)
    inst_id = await _start(session_factory, part["revision_id"], tid, seed["admin_id"])
    status, stage, tasks = await _tasks(session_factory, inst_id)
    assert stage == 1 and not [t for t in tasks if t[3] == "waived"]
    async with session_factory() as s:
        from app.models.workflow import WfInstance
        inst = await s.get(WfInstance, inst_id)
        inst.status = "canceled"
        await s.commit()
    await _sign(session_factory, part["revision_id"], seed["engineer_id"])
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    inst2 = await _start(session_factory, part["revision_id"], tid, seed["admin_id"])
    status, stage, tasks = await _tasks(session_factory, inst2)
    assert stage == 1 and not [t for t in tasks if t[3] == "waived"]
    async with session_factory() as s:
        from app.models.workflow import WfInstance
        (await s.get(WfInstance, inst2)).status = "canceled"
        d = Department(name="Other WF Dept", flow_type="action", is_active=True)
        s.add(d); await s.flush()
        t = WfTemplate(name="other-design-tpl", version=1, is_active=True,
                       created_by=seed["admin_id"])
        s.add(t); await s.flush()
        st = WfStage(template_id=t.id, stage_order=1, name="Design")
        s.add(st); await s.flush()
        step = WfStep(stage_id=st.id, step_name="Update 3D data", position_in_stage=1)
        s.add(step); await s.flush()
        s.add(WfStepRasic(step_id=step.id, department_id=d.id, rasic_letter="R"))
        await s.commit()
        other = t.id
    monkeypatch.setattr(cm_switches, "RELEASE_V2", True)
    inst3 = await _start(session_factory, part["revision_id"], other, seed["admin_id"])
    status, stage, tasks = await _tasks(session_factory, inst3)
    assert stage == 1 and [t[3] for t in tasks] == ["active"]


async def test_signing_leaves_done_tasks_of_a_running_workflow(
        session_factory, seed, part):
    """In flight past Design: an approved step stays approved; only the open
    duplicates of the release checklist are waived; the kept steps run on."""
    from app.models.part import PartRevision
    from app.models.workflow import WfInstanceTask
    from app.services.workflow_service import WorkflowService
    tid = await _template_id(session_factory)
    inst_id = await _start(session_factory, part["revision_id"], tid, seed["admin_id"])
    # walk Design and Design check by hand (two different deciders: 4-eyes)
    for stage_order, actor in ((1, seed["admin_id"]), (2, seed["admin_id"])):
        async with session_factory() as s:
            ids = (await s.execute(select(WfInstanceTask.id).where(
                WfInstanceTask.instance_id == inst_id,
                WfInstanceTask.stage_order == stage_order,
                WfInstanceTask.status == "active"))).scalars().all()
        for task_id in ids:
            async with session_factory() as s:
                await WorkflowService.complete_task(
                    s, task_id, "waived", "walked for the test", actor)
                await s.commit()
    status, stage, _ = await _tasks(session_factory, inst_id)
    assert stage == 3
    async with session_factory() as s:
        rev = await s.get(PartRevision, part["revision_id"])
        rev.no_geometry_change = True
        rev.no_geometry_change_by = seed["engineer_id"]
        await WorkflowService.apply_no_geometry_change(s, rev, seed["engineer_id"])
        await s.commit()
    status, stage, tasks = await _tasks(session_factory, inst_id)
    assert stage == 3
    assert {n for n, _, _, st, _ in tasks if st == "active"} == KEPT
    walked = [notes for n, o, _, st, notes in tasks if o in (1, 2) and st == "waived"]
    assert walked and all(n == "walked for the test" for n in walked)
