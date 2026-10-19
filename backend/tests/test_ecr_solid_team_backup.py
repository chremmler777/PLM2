"""DECIDED BY CHRISTOPH 2026-10-19 (D2b): a named BACKUP per department per
project, next to the responsible. A department task on the project goes to
the responsible; to the backup when the responsible is inactive (or left the
department) or the task is overdue; to the whole department only if neither
is set (legacy). Admin or a Project Management member sets both; PM can
always reassign."""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, ProjectResponsible, UserDepartment
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def team(session_factory, seed):
    """Development: Dana, Ben, Carl. Project Manager: Pat. Quality: Quinn."""
    async with session_factory() as s:
        depts, users = {}, {}
        for i, (name, members) in enumerate((("Development", ("dana", "ben", "carl")),
                                             ("Project Manager", ("pat",)),
                                             ("Quality", ("quinn",)))):
            d = Department(name=name, flow_type="action", is_active=True, sort_order=i)
            s.add(d); await s.flush(); depts[name] = d.id
            for key in members:
                u = User(organization_id=seed["org_id"], username=key,
                         email=f"{key}@test.io", full_name=key.title(),
                         hashed_password=get_password_hash("team-secret-1"),
                         role="engineer", is_active=True, mfa_enabled=False)
                s.add(u); await s.flush()
                s.add(UserDepartment(user_id=u.id, department_id=d.id))
                users[key] = u.id
        await s.commit()
    return {"dept": depts, "user": users}


async def _put(client, seed, headers, **body):
    return await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                            json=body, headers=headers)


async def _team(session_factory, seed, team, responsible="dana", backup="ben"):
    async with session_factory() as s:
        s.add(ProjectResponsible(
            project_id=seed["project_id"], department_id=team["dept"]["Development"],
            user_id=team["user"][responsible] if responsible else None,
            backup_user_id=team["user"][backup] if backup else None))
        await s.commit()


async def _assessment(session_factory, seed, team, due):
    """An in-assessment change with Development's open R assessment."""
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-BK-1", title="backup", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                          status="in_assessment")
        s.add(c); await s.flush()
        a = ChangeAssessment(change_id=c.id, department_id=team["dept"]["Development"],
                             stage_order=1, rasic_letter="R", status="active",
                             due_date=due)
        s.add(a); await s.commit()
        return c.id, a.id


async def _row(client, key, cid):
    res = await client.get("/api/v1/changes/my-tasks",
                           headers=await login(client, f"{key}@test.io", admin=False))
    assert res.status_code == 200, res.text
    rows = [t for t in res.json() if t["kind"] == "assessment" and t["change_id"] == cid]
    assert len(rows) == 1, rows
    return rows[0]


# --- the project team screen ------------------------------------------------

async def test_pm_sets_the_backup_and_the_team_lists_it(client, seed, team):
    pat = await login(client, "pat@test.io", admin=False)
    dev = team["dept"]["Development"]
    res = await _put(client, seed, pat, department_id=dev, user_id=team["user"]["dana"])
    assert res.status_code == 200, res.text
    res = await _put(client, seed, pat, department_id=dev, user_id=team["user"]["ben"],
                     slot="backup")
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r["department_id"] == dev)
    assert row["responsible"]["name"] == "Dana"
    assert row["backup"] == {"id": team["user"]["ben"], "name": "Ben"}
    # clearing the responsible keeps the backup
    res = await _put(client, seed, pat, department_id=dev, user_id=None)
    row = next(r for r in res.json() if r["department_id"] == dev)
    assert row["responsible"] is None and row["backup"]["name"] == "Ben"
    res = await _put(client, seed, pat, department_id=dev, user_id=None, slot="backup")
    row = next(r for r in res.json() if r["department_id"] == dev)
    assert row["backup"] is None


async def test_backup_refusals(client, seed, team):
    """NEGATIVE: only admin or PM sets it; the backup is a member of the
    department and not the responsible."""
    dev = team["dept"]["Development"]
    carl = await login(client, "carl@test.io", admin=False)
    res = await _put(client, seed, carl, department_id=dev, user_id=team["user"]["ben"],
                     slot="backup")
    assert res.status_code == 403
    pat = await login(client, "pat@test.io", admin=False)
    await _put(client, seed, pat, department_id=dev, user_id=team["user"]["dana"])
    res = await _put(client, seed, pat, department_id=dev, user_id=team["user"]["dana"],
                     slot="backup")
    assert res.status_code == 400 and "two different people" in res.json()["detail"]
    res = await _put(client, seed, pat, department_id=dev, user_id=team["user"]["quinn"],
                     slot="backup")
    assert res.status_code == 400 and "member of the Development" in res.json()["detail"]
    res = await _put(client, seed, pat, department_id=dev, user_id=team["user"]["ben"],
                     slot="deputy")
    assert res.status_code == 422


# --- routing ----------------------------------------------------------------

async def test_responsible_main_backup_and_others_back_up(client, seed, team, session_factory):
    await _team(session_factory, seed, team)
    cid, _ = await _assessment(session_factory, seed, team,
                               datetime.utcnow() + timedelta(days=5))
    assert (await _row(client, "dana", cid))["role"] == "main"
    ben = await _row(client, "ben", cid)
    # NEGATIVE: not overdue, the responsible active: the backup is backup
    assert (ben["role"], ben["main_name"]) == ("backup", "Dana")
    assert ben.get("covering_for") is None
    assert (await _row(client, "carl", cid))["role"] == "backup"


async def test_inactive_responsible_routes_to_the_backup(client, seed, team, session_factory):
    await _team(session_factory, seed, team)
    async with session_factory() as s:
        (await s.get(User, team["user"]["dana"])).is_active = False
        await s.commit()
    cid, _ = await _assessment(session_factory, seed, team,
                               datetime.utcnow() + timedelta(days=5))
    assert (await _row(client, "ben", cid))["role"] == "main"
    carl = await _row(client, "carl", cid)
    # NEGATIVE: not the whole department (legacy) while a backup is named
    assert (carl["role"], carl["main_name"]) == ("backup", "Ben")


async def test_backup_alone_owns_it(client, seed, team, session_factory):
    await _team(session_factory, seed, team, responsible=None)
    cid, _ = await _assessment(session_factory, seed, team,
                               datetime.utcnow() + timedelta(days=5))
    assert (await _row(client, "ben", cid))["role"] == "main"
    assert (await _row(client, "carl", cid))["role"] == "backup"


async def test_overdue_task_goes_to_the_backup_too(client, seed, team, session_factory):
    await _team(session_factory, seed, team)
    cid, _ = await _assessment(session_factory, seed, team,
                               datetime.utcnow() - timedelta(days=3))
    ben = await _row(client, "ben", cid)
    assert ben["role"] == "main" and ben["covering_for"] == "Dana"
    # the responsible keeps it as main; the rest of the department does not get it
    assert (await _row(client, "dana", cid))["role"] == "main"
    assert (await _row(client, "carl", cid))["role"] == "backup"


async def test_late_assessment_tells_the_backup_once(client, seed, team, session_factory):
    from app.services import cm_switches
    from app.services.notification_sweep import run_notification_sweep
    if not cm_switches.on("ASSESSMENT_V2"):
        pytest.skip("one escalation rule needs ASSESSMENT_V2")
    await _team(session_factory, seed, team)
    cid, aid = await _assessment(session_factory, seed, team,
                                 datetime.utcnow() - timedelta(days=10))
    for _ in range(2):
        async with session_factory() as s:
            await run_notification_sweep(s); await s.commit()
    async with session_factory() as s:
        ben = (await s.execute(select(Notification).where(
            Notification.user_id == team["user"]["ben"],
            Notification.subject_key == f"assessment:{aid}:overdue:backup"))).scalars().all()
        carl = (await s.execute(select(Notification).where(
            Notification.user_id == team["user"]["carl"],
            Notification.kind == "overdue"))).scalars().all()
    assert len(ben) == 1 and "Dana" in ben[0].body
    assert carl == []          # NEGATIVE: not the whole department


async def test_pm_reassigns_a_department_task(client, seed, team, session_factory):
    cid, aid = await _assessment(session_factory, seed, team,
                                 datetime.utcnow() + timedelta(days=5))
    quinn = await login(client, "quinn@test.io", admin=False)
    res = await client.post(f"/api/v1/changes/{cid}/assessments/{aid}/assign",
                            json={"user_id": team["user"]["carl"]}, headers=quinn)
    assert res.status_code == 400          # NEGATIVE: Quality is not PM
    pat = await login(client, "pat@test.io", admin=False)
    res = await client.post(f"/api/v1/changes/{cid}/assessments/{aid}/assign",
                            json={"user_id": team["user"]["carl"]}, headers=pat)
    assert res.status_code == 200, res.text
    assert res.json()["owner_id"] == team["user"]["carl"]


async def test_permissions_say_who_sets_the_team(client, seed, team):
    """R24: the screen shows its change buttons to who may PUT."""
    pat = await login(client, "pat@test.io", admin=False)
    carl = await login(client, "carl@test.io", admin=False)
    assert (await client.get("/api/v1/changes/permissions", headers=pat)).json()[
        "can_manage_team"] is True
    # NEGATIVE: a Development member does not set the team
    assert (await client.get("/api/v1/changes/permissions", headers=carl)).json()[
        "can_manage_team"] is False
