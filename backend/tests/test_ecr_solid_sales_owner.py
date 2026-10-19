"""ECR-solid C10: the named Sales owner.

- default: the raiser when in Sales, else the project's Sales responsible;
  internal (and mother-plant) changes have none;
- Sales and Project Management change it, to an active Sales member only;
- Sales tasks still show to all of Sales, with the owner's name (the owner
  sees them as "main", the rest of Sales as "backup");
- "Mine" on the list: lead, raiser, Sales owner, or my department owes an
  assessment or a cost input here."""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeChangelog, ChangeRequest
from app.models.entities import User
from app.models.workflow import Department, ProjectResponsible, UserDepartment
from tests.conftest import login

pytestmark = pytest.mark.asyncio
ACTS = "X-Acts-As-Department"


@pytest_asyncio.fixture
async def depts(session_factory, seed):
    ids = {}
    async with session_factory() as s:
        for i, (n, start) in enumerate((("Sales", True), ("Project Manager", True),
                                        ("Development", False), ("Quality", False))):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=start,
                           can_start_internal_change=(n == "Development"))
            s.add(d); await s.flush(); ids[n] = d.id
        await s.commit()
    return ids


@pytest_asyncio.fixture
async def admin(client):
    return await login(client, "admin@test.io")


async def _join(session_factory, user_id, dept_id):
    async with session_factory() as s:
        s.add(UserDepartment(user_id=user_id, department_id=dept_id))
        await s.commit()


async def _sales_user(session_factory, seed, depts, name="Sally Sales"):
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=name.split()[0].lower(),
                 email=f"{name.split()[0].lower()}@test.io", full_name=name,
                 hashed_password="x", role="engineer", is_active=True)
        s.add(u); await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=depts["Sales"]))
        await s.commit()
        return u.id


async def _create(client, headers, seed, customer=True):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "c10", "reason": "r",
        "change_type": "physical_part", "customer_relevant": customer}, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_sales_raiser_owns_it(client, seed, depts, session_factory):
    await _join(session_factory, seed["engineer_id"], depts["Sales"])
    eng = await login(client, "eng@test.io", admin=False)
    c = await _create(client, eng, seed)
    assert c["sales_owner_id"] == seed["engineer_id"]
    assert c["sales_owner_name"] == "Engineer"


async def test_pm_raiser_falls_back_to_the_project_sales_contact(
        client, seed, depts, session_factory, admin):
    sally = await _sales_user(session_factory, seed, depts)
    async with session_factory() as s:
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=depts["Sales"], user_id=sally))
        await s.commit()
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = await _create(client, pm, seed)
    assert c["sales_owner_id"] == sally
    internal = await _create(client, pm, seed, customer=False)
    assert internal["sales_owner_id"] is None


async def test_no_contact_no_owner(client, seed, depts, admin):
    c = await _create(client, {**admin, ACTS: str(depts["Project Manager"])}, seed)
    assert c["sales_owner_id"] is None


async def test_sales_and_pm_change_the_owner(client, seed, depts, session_factory, admin):
    sally = await _sales_user(session_factory, seed, depts)
    c = await _create(client, {**admin, ACTS: str(depts["Project Manager"])}, seed)
    res = await client.patch(f"/api/v1/changes/{c['id']}", json={"sales_owner_id": sally},
                             headers={**admin, ACTS: str(depts["Sales"])})
    assert res.status_code == 200, res.text
    assert res.json()["sales_owner_name"] == "Sally Sales"
    async with session_factory() as s:
        log = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == c["id"]))).scalars().all()
        assert "sales_owner_changed" in log


async def test_owner_change_refused(client, seed, depts, session_factory, admin):
    """Negative: Development may not set it; a non-Sales user cannot own it;
    an internal change has no Sales owner."""
    sally = await _sales_user(session_factory, seed, depts)
    c = await _create(client, {**admin, ACTS: str(depts["Project Manager"])}, seed)
    res = await client.patch(f"/api/v1/changes/{c['id']}", json={"sales_owner_id": sally},
                             headers={**admin, ACTS: str(depts["Development"])})
    assert res.status_code == 403
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"sales_owner_id": seed["engineer_id"]}, headers=admin)
    assert res.status_code == 400
    assert "Sales" in res.json()["detail"]
    internal = await _create(client, admin, seed, customer=False)
    res = await client.patch(f"/api/v1/changes/{internal['id']}",
                             json={"sales_owner_id": sally}, headers=admin)
    assert res.status_code == 400


async def test_sales_tasks_name_the_owner(client, seed, depts, session_factory, admin):
    """All of Sales sees the kickoff, as backup of the lead (D2). With no lead yet the kickoff is Project
    Management's one main row (A6-04): even the owner is backup, naming
    Project Management, until a lead is set."""
    await _join(session_factory, seed["engineer_id"], depts["Sales"])
    eng = await login(client, "eng@test.io", admin=False)
    c = await _create(client, eng, seed)

    async def kickoff(headers):
        return [t for t in (await client.get("/api/v1/changes/my-tasks",
                                             headers=headers)).json()
                if t["change_id"] == c["id"] and t["kind"] == "kickoff"]
    assert c["lead_id"] is None         # the project names no PM
    # NEGATIVE: no lead: the Sales owner is not main yet
    mine = await kickoff(eng)
    assert mine and mine[0]["role"] == "backup"
    assert mine[0]["main_name"] == "Project Management"
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"lead_id": seed["admin_id"]}, headers=admin)
    assert res.status_code == 200, res.text
    # D2 (2026-10-19): the hand-over is the lead's; the Sales contact and
    # the rest of Sales back the lead up
    mine = await kickoff(eng)
    assert mine and mine[0]["role"] == "backup" and not mine[0]["is_mine"]
    assert mine[0]["main_name"] == "Admin"
    rows = await kickoff(admin)
    assert rows and rows[0]["role"] == "main"


async def test_mine_includes_owner_and_owing_department(client, seed, depts,
                                                       session_factory, admin):
    sally = await _sales_user(session_factory, seed, depts)
    c = await _create(client, {**admin, ACTS: str(depts["Project Manager"])}, seed)
    owned = await _create(client, {**admin, ACTS: str(depts["Project Manager"])}, seed)
    await client.patch(f"/api/v1/changes/{owned['id']}", json={"sales_owner_id": sally},
                       headers=admin)
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, c["id"])
        ch.status = "in_assessment"
        s.add(ChangeAssessment(change_id=c["id"], department_id=depts["Development"],
                               rasic_letter="R", status="active"))
        # Quality was only consulted: it owes nothing
        s.add(ChangeAssessment(change_id=c["id"], department_id=depts["Quality"],
                               rasic_letter="C", status="active"))
        await s.commit()

    def mine(rows):
        return {r["id"] for r in rows if r["is_mine"]}
    dev = (await client.get("/api/v1/changes",
                            headers={**admin, ACTS: str(depts["Development"])})).json()
    assert c["id"] in mine(dev) and owned["id"] not in mine(dev)
    quality = (await client.get("/api/v1/changes",
                                headers={**admin, ACTS: str(depts["Quality"])})).json()
    assert mine(quality) == set()
    async with session_factory() as s:
        sally_user = await s.get(User, sally)
        sally_email = sally_user.email
    sales = (await client.get("/api/v1/changes",
                              headers=await login(client, sally_email, admin=False))).json()
    assert mine(sales) == {owned["id"]}


async def test_owner_candidates_are_sales_members(client, seed, depts, session_factory, admin):
    sally = await _sales_user(session_factory, seed, depts)
    c = await _create(client, {**admin, ACTS: str(depts["Project Manager"])}, seed)
    rows = (await client.get(f"/api/v1/changes/{c['id']}/sales-owner-candidates",
                             headers=admin)).json()
    assert [r["id"] for r in rows] == [sally]       # not the engineer, not admin
