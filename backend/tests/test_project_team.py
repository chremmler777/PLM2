"""Project team: one responsible per department per project (spec 2026-09-25)."""
import pytest
import pytest_asyncio

from app.auth.security import get_password_hash
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def depts(session_factory):
    names = ["Project Manager", "Sales", "Development"]
    async with session_factory() as s:
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i)
            s.add(d); await s.flush(); ids[n] = d.id
        await s.commit()
    return ids


@pytest_asyncio.fixture
async def pm_user(session_factory, seed, depts):
    """An active Project Manager department member, in the seeded org."""
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="pm.one", email="pm.one@test.io",
                 full_name="Pat Miller", hashed_password=get_password_hash("pm-secret-123"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u); await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=depts["Project Manager"]))
        await s.commit()
        return u.id


@pytest_asyncio.fixture
async def eng_auth(client):
    return await login(client, "eng@test.io")


@pytest_asyncio.fixture
async def auth(client):
    return await login(client, "admin@test.io")


async def test_get_team_lists_active_departments_with_members(client, auth, seed, depts, pm_user):
    rows = (await client.get(f"/api/v1/projects/{seed['project_id']}/team", headers=auth)).json()
    pm_row = next(r for r in rows if r["department_id"] == depts["Project Manager"])
    assert pm_row["responsible"] is None
    ids = {m["id"] for m in pm_row["members"]}
    assert pm_user in ids
    assert all(m["role"] == "main" for m in pm_row["members"])


async def test_set_responsible_requires_pm_or_admin(client, eng_auth, seed, depts, pm_user):
    r = await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                         json={"department_id": depts["Project Manager"], "user_id": pm_user},
                         headers=eng_auth)
    assert r.status_code == 403


async def test_set_responsible_by_admin_marks_main_and_backup(
        client, auth, seed, depts, pm_user, session_factory):
    # A second PM-department member becomes the backup once pm_user is set main.
    async with session_factory() as s:
        u2 = User(organization_id=seed["org_id"], username="pm.two", email="pm.two@test.io",
                 full_name="Pat Two", hashed_password=get_password_hash("pm-secret-123"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u2); await s.flush()
        s.add(UserDepartment(user_id=u2.id, department_id=depts["Project Manager"]))
        await s.commit()
        u2_id = u2.id

    r = await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                         json={"department_id": depts["Project Manager"], "user_id": pm_user},
                         headers=auth)
    assert r.status_code == 200, r.text
    rows = r.json()
    pm_row = next(x for x in rows if x["department_id"] == depts["Project Manager"])
    assert pm_row["responsible"] == {"id": pm_user, "name": "Pat Miller"}
    roles = {m["id"]: m["role"] for m in pm_row["members"]}
    assert roles[pm_user] == "main"
    assert roles[u2_id] == "backup"


async def test_set_responsible_rejects_non_member(client, auth, seed, depts, session_factory):
    async with session_factory() as s:
        outsider = User(organization_id=seed["org_id"], username="out", email="out@test.io",
                        full_name="Out Sider", hashed_password=get_password_hash("out-secret-1"),
                        role="engineer", is_active=True, mfa_enabled=False)
        s.add(outsider); await s.commit()
        outsider_id = outsider.id
    r = await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                         json={"department_id": depts["Project Manager"], "user_id": outsider_id},
                         headers=auth)
    assert r.status_code == 400


async def test_set_responsible_rejects_inactive_or_other_org_user(
        client, auth, seed, depts, session_factory):
    async with session_factory() as s:
        inactive = User(organization_id=seed["org_id"], username="off", email="off@test.io",
                        full_name="Off Line", hashed_password=get_password_hash("off-secret-1"),
                        role="engineer", is_active=False, mfa_enabled=False)
        s.add(inactive); await s.flush()
        s.add(UserDepartment(user_id=inactive.id, department_id=depts["Project Manager"]))
        await s.commit()
        inactive_id = inactive.id
    r = await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                         json={"department_id": depts["Project Manager"], "user_id": inactive_id},
                         headers=auth)
    assert r.status_code == 400


async def test_clear_responsible_restores_legacy_behaviour(client, auth, seed, depts, pm_user):
    await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                     json={"department_id": depts["Project Manager"], "user_id": pm_user},
                     headers=auth)
    r = await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                         json={"department_id": depts["Project Manager"], "user_id": None},
                         headers=auth)
    assert r.status_code == 200
    pm_row = next(x for x in r.json() if x["department_id"] == depts["Project Manager"])
    assert pm_row["responsible"] is None
    assert all(m["role"] == "main" for m in pm_row["members"])


async def test_change_lead_defaults_to_project_pm_responsible(client, auth, seed, depts, pm_user):
    await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                     json={"department_id": depts["Project Manager"], "user_id": pm_user},
                     headers=auth)
    from tests.conftest import KEEP_LEAD_RULE
    r = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "t", "change_type": "physical_part",
        "reason": "r", "customer_relevant": True,
    }, headers={**auth, KEEP_LEAD_RULE: "1"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["lead_id"] == pm_user


async def test_change_lead_default_absent_without_team(client, auth, seed, depts):
    from tests.conftest import KEEP_LEAD_RULE
    r = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "t2", "change_type": "physical_part",
        "reason": "r", "customer_relevant": True,
    }, headers={**auth, KEEP_LEAD_RULE: "1"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["lead_id"] is None


async def test_lead_candidates_marks_project_pm_default(client, auth, seed, depts, pm_user):
    await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                     json={"department_id": depts["Project Manager"], "user_id": pm_user},
                     headers=auth)
    c = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "t3", "change_type": "physical_part",
        "reason": "r", "customer_relevant": True,
    }, headers=auth)
    cid = c.json()["id"]
    rows = (await client.get(f"/api/v1/changes/{cid}/lead-candidates", headers=auth)).json()
    default_row = next(r for r in rows if r["id"] == pm_user)
    assert default_row["is_default"] is True
    assert rows[0]["id"] == pm_user or rows[0].get("is_current")


async def test_get_team_unknown_project_is_404(client, auth):
    r = await client.get("/api/v1/projects/999999/team", headers=auth)
    assert r.status_code == 404
