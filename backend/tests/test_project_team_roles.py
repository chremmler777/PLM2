"""Project team, the deferred core (spec §18): task lists count main only,
the cockpit splits main from backup, backup acts are audited as
"<backup> for <main>", notifications reach the responsible first."""
import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, ProjectResponsible, UserDepartment
from tests.conftest import login, satisfy_capture_gate

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def team(session_factory, seed):
    """Project Manager, Sales, Development; two members each (one / two)."""
    async with session_factory() as s:
        depts, users = {}, {}
        for i, (name, starter) in enumerate([("Project Manager", False),
                                             ("Sales", True), ("Development", False)]):
            d = Department(name=name, flow_type="action", is_active=True,
                           sort_order=i, can_start_change=starter)
            s.add(d); await s.flush(); depts[name] = d.id
            for n in ("one", "two"):
                key = f"{name.split()[0].lower()}.{n}"
                u = User(organization_id=seed["org_id"], username=key,
                         email=f"{key}@test.io", full_name=f"{name} {n.title()}",
                         hashed_password=get_password_hash("team-secret-1"),
                         role="engineer", is_active=True, mfa_enabled=False)
                s.add(u); await s.flush()
                s.add(UserDepartment(user_id=u.id, department_id=d.id))
                users[key] = u.id
        await s.commit()
    return {"dept": depts, "user": users}


async def _set_responsible(session_factory, project_id, dept_id, user_id):
    async with session_factory() as s:
        s.add(ProjectResponsible(project_id=project_id, department_id=dept_id,
                                 user_id=user_id))
        await s.commit()


async def _change_in(client, session_factory, seed, status, **values):
    from app.models.change import ChangeRequest
    sales = await login(client, "sales.one@test.io")
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "team row", "reason": "r",
        "change_type": "physical_part"}, headers=sales)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    await satisfy_capture_gate(client, sales, cid)
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status = status
        for k, v in values.items():
            setattr(c, k, v)
        await s.commit()
    return cid


async def _rows(client, email, kind, cid):
    res = await client.get("/api/v1/changes/my-tasks",
                           headers=await login(client, email))
    assert res.status_code == 200, res.text
    return [t for t in res.json() if t["kind"] == kind and t["change_id"] == cid]


# --- counting: main vs backup vs no responsible -----------------------------

async def test_without_responsible_every_member_is_main(client, seed, team, session_factory):
    cid = await _change_in(client, session_factory, seed, "scoping")
    for email in ("project.one@test.io", "project.two@test.io"):
        [row] = await _rows(client, email, "scoping_wrapup", cid)
        assert row["role"] == "main"
        assert row["main_name"] is None


async def test_responsible_is_main_other_member_is_backup(client, seed, team, session_factory):
    await _set_responsible(session_factory, seed["project_id"],
                           team["dept"]["Project Manager"], team["user"]["project.one"])
    cid = await _change_in(client, session_factory, seed, "scoping")
    [main] = await _rows(client, "project.one@test.io", "scoping_wrapup", cid)
    assert main["role"] == "main" and main["main_name"] is None
    [backup] = await _rows(client, "project.two@test.io", "scoping_wrapup", cid)
    assert backup["role"] == "backup"
    assert backup["main_name"] == "Project Manager One"


async def test_responsible_elsewhere_does_not_touch_other_roles(
        client, seed, team, session_factory):
    # A Sales responsible leaves Project Management's rows alone.
    await _set_responsible(session_factory, seed["project_id"],
                           team["dept"]["Sales"], team["user"]["sales.one"])
    cid = await _change_in(client, session_factory, seed, "scoping")
    [row] = await _rows(client, "project.two@test.io", "scoping_wrapup", cid)
    assert row["role"] == "main"


async def test_stale_responsible_falls_back_to_everyone_main(
        client, seed, team, session_factory):
    await _set_responsible(session_factory, seed["project_id"],
                           team["dept"]["Project Manager"], team["user"]["project.one"])
    async with session_factory() as s:
        u = await s.get(User, team["user"]["project.one"])
        u.is_active = False
        await s.commit()
    cid = await _change_in(client, session_factory, seed, "scoping")
    [row] = await _rows(client, "project.two@test.io", "scoping_wrapup", cid)
    assert row["role"] == "main"


async def test_team_roles_department_rows_and_ownership(session_factory, seed, team):
    from app.services.project_team_service import TeamRoles
    dev = team["dept"]["Development"]
    await _set_responsible(session_factory, seed["project_id"], dev, team["user"]["development.one"])
    async with session_factory() as s:
        roles = TeamRoles(s, team["user"]["development.two"])
        # a per-department row: its department_id decides
        row = await roles.annotate({"kind": "costing_input", "department_id": dev},
                                   seed["project_id"])
        assert (row["role"], row["main_name"]) == ("backup", "Development One")
        # a fixed-role row: impact_confirm is Development's
        row = await roles.annotate({"kind": "impact_confirm"}, seed["project_id"])
        assert row["role"] == "backup"
        # a row the viewer took (or leads) is theirs
        row = await roles.annotate({"kind": "impact_confirm"}, seed["project_id"], owned=True)
        assert row["role"] == "main"
        # no project: legacy
        row = await roles.annotate({"kind": "impact_confirm"}, None)
        assert row["role"] == "main"
        # the responsible themselves
        main = TeamRoles(s, team["user"]["development.one"])
        row = await main.annotate({"kind": "costing_input", "department_id": dev},
                                  seed["project_id"])
        assert row["role"] == "main"


async def test_intake_rows_carry_the_development_role(client, seed, team, session_factory):
    await _set_responsible(session_factory, seed["project_id"],
                           team["dept"]["Development"], team["user"]["development.one"])
    res = await client.get("/api/v1/intakes/my",
                           headers=await login(client, "development.two@test.io"))
    assert res.status_code == 200, res.text
    assert res.json() == {"triage": [], "review": []} or all(
        r["role"] == "backup" for r in res.json()["triage"])


# --- cockpit: main actions vs "As backup" --------------------------------------

async def test_cockpit_items_carry_role(client, seed, team, session_factory):
    await _set_responsible(session_factory, seed["project_id"],
                           team["dept"]["Development"], team["user"]["development.one"])
    cid = await _change_in(client, session_factory, seed, "scoping")

    async def actions(email):
        res = await client.get(f"/api/v1/changes/{cid}/my-actions",
                               headers=await login(client, email))
        assert res.status_code == 200, res.text
        return {a["kind"]: a for a in res.json()["actions"]}

    main = await actions("development.one@test.io")
    assert main["impact_confirm"]["role"] == "main"
    backup = await actions("development.two@test.io")
    assert backup["impact_confirm"]["role"] == "backup"
    assert backup["impact_confirm"]["main_name"] == "Development One"
    assert "role_department_id" not in backup["impact_confirm"]


# --- audit: "<backup> for <main>" --------------------------------------------

async def test_backup_act_is_audited_as_stand_in(session_factory, seed, team, client):
    from app.models.change import ChangeRequest
    from app.services.change_service import ChangeService
    dev = team["dept"]["Development"]
    await _set_responsible(session_factory, seed["project_id"], dev, team["user"]["development.one"])
    cid = await _change_in(client, session_factory, seed, "costing")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        backup_entry = await ChangeService.append_changelog(
            s, change, "cost_lines_updated", "lines", team["user"]["development.two"],
            new_value={"lines": 2}, notes="checked", for_department_id=dev)
        main_entry = await ChangeService.append_changelog(
            s, change, "cost_lines_updated", "lines", team["user"]["development.one"],
            new_value={"lines": 3}, for_department_id=dev)
        await s.commit()
    assert backup_entry.notes == "Development Two for Development One: checked"
    stand_in = json.loads(backup_entry.new_value)["stands_in_for"]
    assert stand_in == {"user_id": team["user"]["development.one"],
                        "name": "Development One", "department_id": dev}
    assert main_entry.notes is None
    assert "stands_in_for" not in json.loads(main_entry.new_value)


async def test_stand_in_absent_without_responsible(session_factory, seed, team):
    from app.services.project_team_service import ProjectTeamService
    async with session_factory() as s:
        assert await ProjectTeamService.stand_in(
            s, seed["project_id"], team["dept"]["Sales"], team["user"]["sales.two"]) is None


async def test_release_check_by_backup_records_stand_in(client, seed, team, session_factory):
    """End to end through a real act: a release check answered by a backup."""
    from app.models.change import ChangeChangelog, ChangeRequest
    from app.services.release_service import ReleaseService
    dev = team["dept"]["Development"]
    await _set_responsible(session_factory, seed["project_id"], dev, team["user"]["development.one"])
    cid = await _change_in(client, session_factory, seed, "in_validation")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        user = await s.get(User, team["user"]["development.two"])
        await ReleaseService.set_check(s, change, "index_updated", "done", None, user)
        await s.commit()
        entry = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "release_check"))).scalars().one()
    assert entry.notes == "Development Two for Development One"
    assert json.loads(entry.new_value)["stands_in_for"]["name"] == "Development One"


# --- notifications: responsible first, backups as info ------------------------

async def test_notify_team_marks_backups_as_info(session_factory, seed, team):
    from app.services.notification_service import NotificationService
    sales = team["dept"]["Sales"]
    await _set_responsible(session_factory, seed["project_id"], sales, team["user"]["sales.one"])
    async with session_factory() as s:
        n = await NotificationService.notify_team(
            s, seed["project_id"], [sales], title="T", body="B", link="/x")
        await s.commit()
        assert n == 2
        rows = {r.user_id: r for r in (await s.execute(select(Notification))).scalars()}
    assert rows[team["user"]["sales.one"]].body == "B"
    assert rows[team["user"]["sales.two"]].body == "B\nInfo: you are backup here, main: Sales One."


async def test_notify_team_without_responsible_is_todays_behaviour(session_factory, seed, team):
    from app.services.notification_service import NotificationService
    sales = team["dept"]["Sales"]
    async with session_factory() as s:
        await NotificationService.notify_team(
            s, seed["project_id"], [sales], title="T", body="B",
            kind="k", subject_key="s")
        await s.commit()
        bodies = [r.body for r in (await s.execute(select(Notification))).scalars()]
    assert bodies == ["B", "B"]


# --- review fixes: recipients, stand-in, badge count ---------------------------

async def test_notify_team_default_recipients_are_active_members_of_the_org(
        session_factory, seed, team):
    from app.models.entities import Organization
    from app.services.notification_service import NotificationService
    sales = team["dept"]["Sales"]
    async with session_factory() as s:
        (await s.get(User, team["user"]["sales.two"])).is_active = False
        other = Organization(name="Other", code="other-org", is_active=True)
        s.add(other); await s.flush()
        u = User(organization_id=other.id, username="sales.far", email="sales.far@test.io",
                 full_name="Sales Far", hashed_password=get_password_hash("team-secret-1"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u); await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=sales))
        await s.commit()
        n = await NotificationService.notify_team(
            s, seed["project_id"], [sales], title="T", body="B")
        await s.commit()
        got = sorted(r.user_id for r in (await s.execute(select(Notification))).scalars())
    assert n == 1 and got == [team["user"]["sales.one"]]


async def test_stand_in_only_for_members_and_new_value_keeps_its_shape(
        session_factory, seed, team, client):
    from app.models.change import ChangeRequest
    from app.services.change_service import ChangeService
    from app.services.project_team_service import ProjectTeamService
    dev = team["dept"]["Development"]
    await _set_responsible(session_factory, seed["project_id"], dev, team["user"]["development.one"])
    cid = await _change_in(client, session_factory, seed, "costing")
    async with session_factory() as s:
        # an admin (or PM, lead) outside Development is nobody's backup
        assert await ProjectTeamService.stand_in(
            s, seed["project_id"], dev, seed["admin_id"]) is None
        assert await ProjectTeamService.stand_in(
            s, seed["project_id"], dev, team["user"]["project.one"]) is None
        change = await s.get(ChangeRequest, cid)
        admin_entry = await ChangeService.append_changelog(
            s, change, "x", "d", seed["admin_id"], new_value={"a": 1},
            for_department_id=dev)
        scalar = await ChangeService.append_changelog(
            s, change, "x", "d", team["user"]["development.two"], new_value=12.5,
            for_department_id=dev)
        empty = await ChangeService.append_changelog(
            s, change, "x", "d", team["user"]["development.two"],
            for_department_id=dev)
        await s.commit()
    assert json.loads(admin_entry.new_value) == {"a": 1} and admin_entry.notes is None
    # a scalar stays the scalar; the stand-in is in the notes
    assert json.loads(scalar.new_value) == 12.5
    assert scalar.notes == "Development Two for Development One"
    assert empty.new_value is None and empty.notes == "Development Two for Development One"


async def test_open_task_count_is_the_badge_number(client, seed, team, session_factory):
    pm = team["dept"]["Project Manager"]
    cid = await _change_in(client, session_factory, seed, "scoping")

    async def count(email):
        res = await client.get("/api/v1/workflow-instances/open-task-count",
                               headers=await login(client, email))
        assert res.status_code == 200, res.text
        return res.json()["count"]

    async def badge(email):
        h = await login(client, email)
        wf = (await client.get("/api/v1/workflow-instances/my-tasks", headers=h)).json()
        ch = (await client.get("/api/v1/changes/my-tasks", headers=h)).json()
        it = (await client.get("/api/v1/intakes/my", headers=h)).json()
        fin = (await client.get("/api/v1/cost-sheet/review-task", headers=h)).json()
        folded = {}
        for r in ch:
            k = (r["change_id"], r["kind"], r.get("department_id"))
            folded[k] = folded.get(k, True) and r.get("role") == "backup"
        return (sum(1 for r in wf if r.get("role") != "backup")
                + sum(1 for b in folded.values() if not b)
                + sum(1 for r in it["triage"] + it["review"] if r.get("role") != "backup")
                + (1 if fin["due"] else 0))

    one = await count("project.one@test.io")
    assert one >= 1 and one == await badge("project.one@test.io")
    await _set_responsible(session_factory, seed["project_id"], pm, team["user"]["project.one"])
    two = await count("project.two@test.io")
    assert two == await badge("project.two@test.io") and two == one - len(
        await _rows(client, "project.two@test.io", "scoping_wrapup", cid))
