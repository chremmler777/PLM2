"""F16 (test 2026-10-26): the Tool Engineer closes the tool change with a
real task, no override in the happy path: the guard reads the Tool
Engineer's R only (Project Management's A on the step does not hold the
tool), and the Tool Engineer's "our part done" approves the open
"Implement tool change" task."""
import pytest
from sqlalchemy import select

from tests.conftest import make_department_member
from tests.test_ecr_solid_tool_change_owner import _tool_change_world

pytestmark = pytest.mark.asyncio


async def _with_pm_a(session_factory, cid):
    from app.models.change import ChangeImpactedItem
    from app.models.workflow import Department, WfInstance, WfInstanceTask
    async with session_factory() as s:
        rev = (await s.execute(select(ChangeImpactedItem.resulting_revision_id).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.part_revision_id == rev))).scalar_one()
        r = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id))).scalar_one()
        pm = (await s.execute(select(Department.id).where(
            Department.name == "Project Manager"))).scalar_one()
        s.add(WfInstanceTask(instance_id=inst.id, stage_order=3, step_id=r.step_id,
                             department_id=pm, rasic_letter="A", status="active",
                             is_actionable=True))
        await s.commit()
        return r.id


async def test_pm_a_alone_does_not_hold_the_tool(session_factory, seed):
    from app.models.workflow import WfInstanceTask
    from app.services.change_service import ChangeService
    cid = await _tool_change_world(session_factory, seed, done=False)
    r_id = await _with_pm_a(session_factory, cid)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        assert await ChangeService.open_tool_changes(s, change) == ["T-3454"]
        (await s.get(WfInstanceTask, r_id)).status = "approved"
        await s.commit()
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        assert await ChangeService.open_tool_changes(s, change) == []


async def test_tool_engineers_our_part_done_closes_the_tool_change(
        session_factory, seed, monkeypatch):
    from app.models.entities import User
    from app.services.change_service import ChangeService
    from app.services.implementation_service import ImplementationService
    cid = await _tool_change_world(session_factory, seed, done=False)
    await _with_pm_a(session_factory, cid)
    te = await make_department_member(session_factory, seed["engineer_id"], "Tool Engineer")

    async def implementing(session, change):
        return [te]
    monkeypatch.setattr(ImplementationService, "implementing_department_ids",
                        staticmethod(implementing))
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        actor = await s.get(User, seed["engineer_id"])
        await ImplementationService.create_report(
            s, change, {"department_id": te, "note": "tool modified, T1 ok",
                        "part_done": True}, actor)
        await s.commit()
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        assert await ChangeService.open_tool_changes(s, change) == []


async def test_negative_another_departments_part_done_leaves_the_tool_open(
        session_factory, seed, monkeypatch):
    from app.models.entities import User
    from app.services.change_service import ChangeService
    from app.services.implementation_service import ImplementationService
    cid = await _tool_change_world(session_factory, seed, done=False)
    proc = await make_department_member(session_factory, seed["engineer_id"], "Process Engineer")

    async def implementing(session, change):
        return [proc]
    monkeypatch.setattr(ImplementationService, "implementing_department_ids",
                        staticmethod(implementing))
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        actor = await s.get(User, seed["engineer_id"])
        await ImplementationService.create_report(
            s, change, {"department_id": proc, "note": "sheets done",
                        "part_done": True}, actor)
        await s.commit()
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        assert await ChangeService.open_tool_changes(s, change) == ["T-3454"]
