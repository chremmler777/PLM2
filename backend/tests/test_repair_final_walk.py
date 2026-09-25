"""scripts/repair_final_walk step 3: an escalated review gets the project's
PM responsible as lead unless a lead was chosen after the escalation, and a
second run changes nothing."""
import pytest
from sqlalchemy import select

from app.models.change import ChangeChangelog, ChangeRequest
from app.models.workflow import Department, ProjectResponsible, UserDepartment
from scripts.repair_final_walk import repair_escalated_reviews

pytestmark = pytest.mark.asyncio


async def _escalated(s, seed, number):
    from app.services.change_service import ChangeService
    change = await ChangeService.create_change(
        s, project_id=seed["project_id"], title=f"review {number}",
        change_type="physical_part", raised_by=seed["engineer_id"],
        reason="r", lead_id=seed["engineer_id"])
    change.title_auto = False
    await s.flush()
    await ChangeService.append_changelog(
        s, change, "review_escalated", "Escalated to a full ECR",
        seed["engineer_id"])
    return change


async def _leads(s):
    return dict((await s.execute(
        select(ChangeRequest.id, ChangeRequest.lead_id))).all())


async def _entries(s):
    return (await s.execute(select(ChangeChangelog.id))).scalars().all()


async def test_lead_follows_pm_once_and_respects_a_later_choice(session_factory, seed):
    from app.services.change_service import ChangeService
    admin, eng = seed["admin_id"], seed["engineer_id"]
    async with session_factory() as s:
        pm_dept = Department(name="Project Manager", flow_type="action", is_active=True)
        s.add(pm_dept); await s.flush()
        s.add(UserDepartment(user_id=admin, department_id=pm_dept.id))
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=pm_dept.id, user_id=admin))
        still_reviewer = await _escalated(s, seed, 1)
        chosen = await _escalated(s, seed, 2)
        # someone picked a lead by hand after the escalation
        chosen.lead_id = seed["inactive_id"]
        await ChangeService.append_changelog(
            s, chosen, "lead_changed", "picked", eng, field_name="lead_id",
            old_value=eng, new_value=seed["inactive_id"])
        await s.commit()

    async with session_factory() as s:
        report = await repair_escalated_reviews(s, admin)
        await s.commit()
    assert len(report) == 1
    async with session_factory() as s:
        leads = await _leads(s)
        assert leads[still_reviewer.id] == admin          # reviewer -> PM
        assert leads[chosen.id] == seed["inactive_id"]    # hand pick kept
        entries = await _entries(s)

    # second run: nothing changes, nothing is audited
    async with session_factory() as s:
        assert await repair_escalated_reviews(s, admin) == []
        await s.commit()
    async with session_factory() as s:
        assert await _leads(s) == leads
        assert await _entries(s) == entries

    # a lead chosen after the repair is kept too
    async with session_factory() as s:
        c = await ChangeService.get_change(s, still_reviewer.id)
        c.lead_id = seed["inactive_id"]
        await ChangeService.append_changelog(
            s, c, "lead_changed", "picked", admin, field_name="lead_id",
            old_value=admin, new_value=seed["inactive_id"])
        await s.commit()
    async with session_factory() as s:
        assert await repair_escalated_reviews(s, admin) == []
