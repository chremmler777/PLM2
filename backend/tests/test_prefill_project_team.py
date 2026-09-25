"""scripts/prefill_project_team.py: matches projects and users by name,
dry run by default, refuses to guess, idempotent, writes the role keys the
project team service reads."""
import importlib.util
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models.entities import Project, User
from app.models.workflow import Department, ProjectResponsible, UserDepartment
from app.services.project_team_service import ProjectTeamService

pytestmark = pytest.mark.asyncio

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prefill_project_team.py"
DEPTS = ["Project Manager", "Manufacturing Engineer", "Tool Engineer", "APQP", "Development"]


def _load():
    spec = importlib.util.spec_from_file_location("prefill_project_team", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod        # dataclasses resolve their module
    spec.loader.exec_module(mod)
    return mod


mod = _load()


async def _user(s, org_id, username, full_name=None, email=None, active=True):
    u = User(organization_id=org_id, username=username, email=email or f"{username}@t.io",
             full_name=full_name or username, hashed_password="x", role="admin",
             is_active=active, mfa_enabled=False)
    s.add(u)
    await s.flush()
    return u


@pytest_asyncio.fixture
async def world(session_factory, seed):
    """The prod shape: SSO users whose full name is the username, the
    Christoph duplicate accounts, three projects plus a near miss."""
    async with session_factory() as s:
        plant_id = (await s.get(Project, seed["project_id"])).plant_id
        dept = {}
        for i, n in enumerate(DEPTS + ["Tooling Engineer"]):
            d = Department(name=n, flow_type="action", is_active=n != "Tooling Engineer",
                           sort_order=i)
            s.add(d)
            await s.flush()
            dept[n] = d.id
        proj = {}
        for code, name in (("1994", "Brose Seat Trim"), ("1994A", "Brose 1994 old import"),
                           ("2277", "Brose Backpanel"), ("1864", "VW426 Atlas")):
            p = Project(plant_id=plant_id, name=name, code=code, status="active")
            s.add(p)
            await s.flush()
            proj[code] = p.id
        org = seed["org_id"]
        users = {
            "cody": await _user(s, org, "cody.hrtyanski"),
            "russ": await _user(s, org, "russell.b", "Russell Brown"),
            "dale": await _user(s, org, "dale.perry"),
            "george": await _user(s, org, "george.k", "George Kim"),
            "apurva": await _user(s, org, "apurvam"),
            "christoph": await _user(s, org, "christoph.demmler"),
            "christoph2": await _user(s, org, "christoph.demmler-1", "christoph.demmler",
                                      email="christoph.demmler@us.ktx.group"),
            "chris": await _user(s, org, "chris", "Christoph", email="chris@example.com"),
        }
        who = {"Project Manager": ["cody"], "Manufacturing Engineer": ["russ"],
               "Tool Engineer": ["dale"], "APQP": ["george", "apurva"],
               "Development": ["christoph", "christoph2"]}
        for d, keys in who.items():
            for k in keys:
                s.add(UserDepartment(user_id=users[k].id, department_id=dept[d]))
        await s.commit()
        return {"dept": dept, "proj": proj, "user": {k: u.id for k, u in users.items()}}


async def _count(session_factory, model):
    async with session_factory() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar()


async def test_role_keys_are_the_service_department_names():
    from app.services import project_team_service as svc
    assert {svc.PM, svc.DEVELOPMENT} <= set(mod.BASE_TEAM)
    assert set(mod.BASE_TEAM) == set(DEPTS)
    assert mod.TEAM["VW426"]["APQP"].label == "Apurva M."
    assert mod.TEAM["1994"]["APQP"].label == mod.TEAM["2277"]["APQP"].label == "George"


async def test_dry_run_plans_everything_and_writes_nothing(session_factory, world):
    async with session_factory() as s:
        plan = await mod.plan_team(s)
    assert len(plan.rows) == 15 and not plan.problems
    assert {r.status for r in plan.rows} == {"set"}
    got = {(r.project_token, r.department): r.user_id for r in plan.rows}
    u, p = world["user"], world["proj"]
    assert got[("1994", "APQP")] == u["george"]
    assert got[("VW426", "APQP")] == u["apurva"]
    assert got[("2277", "Manufacturing Engineer")] == u["russ"]      # Russ -> Russell (fuzzy)
    assert got[("1994", "Development")] == u["christoph"]            # exact username wins
    assert {r.project_id for r in plan.rows if r.project_token == "1994"} == {p["1994"]}
    assert {r.project_id for r in plan.rows if r.project_token == "VW426"} == {p["1864"]}
    assert any("Christoph" in n and "chris" in n for n in plan.notes)
    assert await _count(session_factory, ProjectResponsible) == 0


async def test_apply_is_read_by_the_service_and_idempotent(session_factory, world):
    u, p = world["user"], world["proj"]
    async with session_factory() as s:
        plan = await mod.plan_team(s)
        counts = await mod.apply_plan(s, plan, actor_id=u["christoph"])
        await s.commit()
    assert counts["set"] == 15
    async with session_factory() as s:
        rid = ProjectTeamService.responsible_user_id
        assert await rid(s, p["1994"], "Project Manager") == u["cody"]
        assert await rid(s, p["1994"], "APQP") == u["george"]
        assert await rid(s, p["1864"], "APQP") == u["apurva"]
        assert await rid(s, p["2277"], "Tool Engineer") == u["dale"]
        assert await rid(s, p["1864"], "Development") == u["christoph"]
        team = await ProjectTeamService.list_team(s, p["2277"])
        mfg = next(t for t in team if t["department_name"] == "Manufacturing Engineer")
        assert mfg["responsible"]["id"] == u["russ"]
        dev = next(t for t in team if t["department_name"] == "Development")
        assert {m["id"]: m["role"] for m in dev["members"]}[u["christoph2"]] == "backup"
        again = await mod.plan_team(s)
        assert {r.status for r in again.rows} == {"unchanged"}
        counts = await mod.apply_plan(s, again)
        await s.commit()
    assert counts == {"set": 0, "replace": 0, "unchanged": 15, "memberships": 0}
    assert await _count(session_factory, ProjectResponsible) == 15


async def test_ambiguous_user_is_refused_until_pinned(session_factory, world, monkeypatch,
                                                      db_engine):
    async with session_factory() as s:
        g2 = await _user(s, (await s.get(User, world["user"]["george"])).organization_id,
                         "george.miller", "George Miller")
        s.add(UserDepartment(user_id=g2.id, department_id=world["dept"]["APQP"]))
        await s.commit()
    async with session_factory() as s:
        plan = await mod.plan_team(s)
    bad = {(r.project_token, r.department) for r in plan.problems}
    assert bad == {("1994", "APQP"), ("2277", "APQP")}
    assert all(r.status == "ambiguous_user" and "george.miller" in r.detail
               for r in plan.problems)

    # The CLI refuses to apply anything while a row is ambiguous.
    monkeypatch.setenv("DATABASE_URL", str(db_engine.url))
    assert await mod.main(["--apply"]) == 2
    assert await _count(session_factory, ProjectResponsible) == 0

    # Pinned: resolved, applied.
    assert await mod.main(["--apply", f"--user-id=George={world['user']['george']}"]) == 0
    async with session_factory() as s:
        assert await ProjectTeamService.responsible_user_id(
            s, world["proj"]["1994"], "APQP") == world["user"]["george"]
    assert await _count(session_factory, ProjectResponsible) == 15


async def test_dry_run_cli_writes_nothing(session_factory, world, monkeypatch, db_engine,
                                          capsys):
    monkeypatch.setenv("DATABASE_URL", str(db_engine.url))
    assert await mod.main([]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert await _count(session_factory, ProjectResponsible) == 0


async def test_ambiguous_project_is_refused(session_factory, world):
    async with session_factory() as s:
        s.add(Project(plant_id=(await s.get(Project, world["proj"]["1864"])).plant_id,
                      name="VW426 Atlas facelift", code="1901", status="active"))
        await s.commit()
    async with session_factory() as s:
        plan = await mod.plan_team(s)
        vw = [r for r in plan.rows if r.project_token == "VW426"]
        assert {r.status for r in vw} == {"ambiguous_project"}
        assert not [r for r in plan.problems if r.project_token != "VW426"]
        pinned = await mod.plan_team(s, project_ids={"VW426": world["proj"]["1864"]})
        assert not pinned.problems


async def test_membership_and_existing_responsible_are_not_overridden(session_factory, world):
    u, d, p = world["user"], world["dept"], world["proj"]
    async with session_factory() as s:
        await s.execute(UserDepartment.__table__.delete().where(
            UserDepartment.user_id == u["dale"]))
        s.add(ProjectResponsible(project_id=p["1994"], department_id=d["Project Manager"],
                                 user_id=u["christoph"]))
        s.add(UserDepartment(user_id=u["christoph"], department_id=d["Project Manager"]))
        await s.commit()
    async with session_factory() as s:
        plan = await mod.plan_team(s)
        st = {(r.project_token, r.department): r.status for r in plan.rows}
        assert st[("1994", "Tool Engineer")] == "not_member"
        assert st[("1994", "Project Manager")] == "taken"
        assert st[("2277", "Project Manager")] == "set"

        plan = await mod.plan_team(s, add_membership=True, replace=True)
        assert not plan.problems
        st = {(r.project_token, r.department): r.status for r in plan.rows}
        assert st[("1994", "Project Manager")] == "replace"
        counts = await mod.apply_plan(s, plan)
        await s.commit()
    assert counts["memberships"] == 1 and counts["replace"] == 1
    async with session_factory() as s:
        assert await ProjectTeamService.responsible_user_id(
            s, p["1994"], "Tool Engineer") == u["dale"]
        assert await ProjectTeamService.responsible_user_id(
            s, p["1994"], "Project Manager") == u["cody"]


async def test_missing_user_reports_and_never_matches_inactive(session_factory, world):
    async with session_factory() as s:
        cody = await s.get(User, world["user"]["cody"])
        cody.is_active = False
        await s.commit()
    async with session_factory() as s:
        plan = await mod.plan_team(s)
    pm = [r for r in plan.rows if r.department == "Project Manager"]
    assert {r.status for r in pm} == {"no_user"}
    assert all("inactive matches" in r.detail and "cody.hrtyanski" in r.detail for r in pm)
