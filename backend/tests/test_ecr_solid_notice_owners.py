"""F7 + F6 + F11 + T7/T16 (test 2026-10-26, R33): a notice reaches who owns
the work: the project team's responsible per department (the named backup
when the responsible is out), else the department's members; never a
placeholder/local account, never a member the team does not name; the
stage notice is not sent on top of the task notice; sign-off notices
follow the project team."""
import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.core.config import get_settings
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, ProjectResponsible, UserDepartment

pytestmark = pytest.mark.asyncio


async def _dept_with(s, seed, name, people, hub=True):
    d = Department(name=name, flow_type="action", is_active=True)
    s.add(d)
    await s.flush()
    ids = []
    for p in people:
        u = User(organization_id=seed["org_id"], username=p, email=f"{p}@test.io",
                 full_name=p.title(), role="engineer", is_active=True, mfa_enabled=False,
                 hashed_password="!" if hub else get_password_hash("x-secret-12"))
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=d.id))
        ids.append(u.id)
    return d.id, ids


async def _told(s):
    return sorted((await s.execute(select(Notification.user_id))).scalars().all())


async def test_responsible_only_then_backup_then_members(session_factory, seed):
    from app.services.notification_service import NotificationService
    async with session_factory() as s:
        q, (sonja, eric, udo) = await _dept_with(s, seed, "Quality", ["sonja", "eric", "udo"])
        s.add(ProjectResponsible(project_id=seed["project_id"], department_id=q,
                                 user_id=sonja, backup_user_id=eric))
        await s.commit()
        await NotificationService.notify_team(s, seed["project_id"], [q], title="T")
        await s.commit()
        assert await _told(s) == [sonja]
        (await s.get(User, sonja)).is_active = False
        await s.commit()
        await NotificationService.notify_team(s, seed["project_id"], [q], title="T2")
        await s.commit()
        assert await _told(s) == [sonja, eric]


async def test_negative_placeholder_accounts_are_never_told(session_factory, seed, monkeypatch):
    from app.services.notification_service import NotificationService
    monkeypatch.setattr(get_settings(), "local_users_as_members", False)
    async with session_factory() as s:
        d, (real,) = await _dept_with(s, seed, "Development", ["real.dev"])
        _, (local,) = await _dept_with(s, seed, "Development2", ["testuser"], hub=False)
        s.add(UserDepartment(user_id=local, department_id=d))
        await s.commit()
        await NotificationService.notify_team(s, seed["project_id"], [d], title="T")
        await s.commit()
        assert await _told(s) == [real]


async def test_stage_notice_not_on_top_of_the_task_notice(session_factory, seed):
    from app.services.notification_service import NotificationService
    async with session_factory() as s:
        d, (a, b) = await _dept_with(s, seed, "Process Engineer", ["holmes", "payne"])
        await s.commit()
        await NotificationService.notify_users(s, [a], "Your task", kind="task_new")
        await NotificationService.notify_team(
            s, seed["project_id"], [d], title="Change entered assessment",
            kind="stage_entered", subject_key="chg:1:in_assessment")
        await s.commit()
        rows = (await s.execute(select(Notification.user_id, Notification.kind))).all()
    assert sorted(rows) == sorted([(a, "task_new"), (b, "stage_entered")])


async def test_sign_off_notice_goes_to_the_team_pm_not_every_pm(session_factory, seed):
    from types import SimpleNamespace
    from app.services import decision_notices
    async with session_factory() as s:
        pm, (cody, steven, carlos) = await _dept_with(
            s, seed, "Project Manager", ["cody", "steven", "carlos"])
        s.add(ProjectResponsible(project_id=seed["project_id"], department_id=pm,
                                 user_id=cody, backup_user_id=steven))
        await s.commit()
        change = SimpleNamespace(project_id=seed["project_id"])
        assert await decision_notices._members(s, change, "Project Manager") == [cody]
        # the 4-eyes exclusion steps to the backup, never to the rest
        assert await decision_notices._members(
            s, change, "Project Manager", exclude=(cody,)) == [steven]
