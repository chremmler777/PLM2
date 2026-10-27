"""esc P1-1 + P1-2 (test 2026-10-26): the sweep tells the department's
project-team RESPONSIBLE, claimed or not, on the due date and when late;
the responsible inactive or gone, the named backup owns the item and gets
the notices. One notice per item and person."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import (
    Department, ProjectResponsible, UserDepartment, WfInstance, WfInstanceTask, WfTemplate)
from app.services import due_rules
from app.services.notification_sweep import run_notification_sweep

pytestmark = pytest.mark.asyncio


async def _world(s, seed):
    d = Department(name="Process Engineer", flow_type="action", is_active=True)
    s.add(d)
    await s.flush()
    ids = {}
    for name in ("holmes", "payne", "other"):
        u = User(organization_id=seed["org_id"], username=name, email=f"{name}@test.io",
                 full_name=name.title(), hashed_password=get_password_hash("x-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=d.id))
        ids[name] = u.id
    s.add(ProjectResponsible(project_id=seed["project_id"], department_id=d.id,
                             user_id=ids["holmes"], backup_user_id=ids["payne"]))
    c = ChangeRequest(change_number="C-SR-1", title="t", reason="r",
                      change_type="physical_part", project_id=seed["project_id"],
                      raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                      status="in_assessment")
    s.add(c)
    await s.flush()
    tmpl = WfTemplate(name="sr", version=1, is_active=True, created_by=1)
    s.add(tmpl)
    await s.flush()
    inst = WfInstance(template_id=tmpl.id, change_id=c.id, status="active",
                      current_stage_order=1, started_by=seed["admin_id"])
    s.add(inst)
    await s.flush()
    return d, c, inst, ids


async def _notes(s, uid, kind):
    return (await s.execute(select(Notification).where(
        Notification.user_id == uid, Notification.kind == kind))).scalars().all()


async def test_unclaimed_task_due_today_and_late_tells_the_responsible(session_factory, seed):
    now = datetime.utcnow()
    async with session_factory() as s:
        d, c, inst, ids = await _world(s, seed)
        today = WfInstanceTask(instance_id=inst.id, stage_order=1, department_id=d.id,
                               rasic_letter="R", status="active", is_actionable=True,
                               due_date=now.replace(hour=23, minute=59))
        late = WfInstanceTask(instance_id=inst.id, stage_order=1, department_id=d.id,
                              rasic_letter="R", status="active", is_actionable=True,
                              due_date=due_rules.sub_wd(now, 2))
        s.add_all([today, late])
        await s.commit()
        await run_notification_sweep(s)
        await s.commit()
        await run_notification_sweep(s)   # a second run repeats nothing
        await s.commit()
        assert [n.subject_key for n in await _notes(s, ids["holmes"], "due_soon")] == [
            f"task:{today.id}:due_soon"]
        late_keys = sorted(n.subject_key for n in await _notes(s, ids["holmes"], "overdue"))
        assert late_keys == [f"task:{late.id}:overdue"]
        # the named backup hears the late one once (escalation), the rest of
        # the department nothing
        assert [n.subject_key for n in await _notes(s, ids["payne"], "overdue")] == [
            f"task:{late.id}:overdue:backup"]
        assert not await _notes(s, ids["payne"], "due_soon")
        assert not await _notes(s, ids["other"], "overdue")
        assert not await _notes(s, ids["other"], "due_soon")


async def test_inactive_responsible_the_backup_owns_and_is_told(session_factory, seed):
    now = datetime.utcnow()
    async with session_factory() as s:
        d, c, inst, ids = await _world(s, seed)
        (await s.get(User, ids["holmes"])).is_active = False
        late = ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                                rasic_letter="R", due_date=due_rules.sub_wd(now, 2))
        today = ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                                 rasic_letter="R", due_date=now.replace(hour=23, minute=59))
        s.add_all([late, today])
        await s.commit()
        await run_notification_sweep(s)
        await s.commit()
        assert [n.subject_key for n in await _notes(s, ids["payne"], "overdue")] == [
            f"assessment:{late.id}:overdue"]
        assert [n.subject_key for n in await _notes(s, ids["payne"], "due_soon")] == [
            f"assessment:{today.id}:due_soon"]
        assert not await _notes(s, ids["holmes"], "overdue")
        assert not await _notes(s, ids["other"], "overdue")
