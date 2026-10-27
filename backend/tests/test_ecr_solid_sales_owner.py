"""ECR-solid C10: the named Sales owner.

- default (Christoph 2026-10-26, migration 152: Project Management
  captures, Sales no longer starts changes): the project's Sales
  responsible, else its named backup, else nobody (PM picks a Sales
  member); internal (and mother-plant) changes have none;
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
        for i, (n, start) in enumerate((("Sales", False), ("Project Manager", True),
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


async def test_sales_no_longer_captures(client, seed, depts, session_factory):
    """Migration 152: a Sales member starts no change, customer or internal,
    and the permissions answer says so."""
    await _join(session_factory, seed["engineer_id"], depts["Sales"])
    eng = await login(client, "eng@test.io", admin=False)
    for customer in (True, False):
        res = await client.post("/api/v1/changes", json={
            "project_id": seed["project_id"], "title": "c10", "reason": "r",
            "change_type": "physical_part", "customer_relevant": customer},
            headers=eng)
        assert res.status_code == 403, res.text
        assert "Project Management starts customer changes" in res.json()["detail"]
    perms = (await client.get("/api/v1/changes/permissions", headers=eng)).json()
    assert perms["can_start_change"] is False
    assert perms["can_start_internal_change"] is False


async def test_pm_raiser_in_sales_too_is_not_the_contact(
        client, seed, depts, session_factory):
    """The raiser is no Sales contact any more: a PM who also sits in Sales
    raises a change whose contact is the project's Sales responsible."""
    sally = await _sales_user(session_factory, seed, depts)
    await _join(session_factory, seed["engineer_id"], depts["Sales"])
    await _join(session_factory, seed["engineer_id"], depts["Project Manager"])
    async with session_factory() as s:
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=depts["Sales"], user_id=sally))
        await s.commit()
    eng = await login(client, "eng@test.io", admin=False)
    c = await _create(client, eng, seed)
    assert c["sales_owner_id"] == sally


async def test_backup_is_the_contact_without_a_responsible(
        client, seed, depts, session_factory, admin):
    """No live Sales responsible on the project: its named backup is the
    contact (a responsible who left Sales does not count)."""
    sally = await _sales_user(session_factory, seed, depts)
    bob = await _sales_user(session_factory, seed, depts, name="Bob Backup")
    async with session_factory() as s:
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=depts["Sales"], user_id=None,
                                 backup_user_id=bob))
        await s.commit()
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = await _create(client, pm, seed)
    assert c["sales_owner_id"] == bob
    async with session_factory() as s:
        row = (await s.execute(select(ProjectResponsible).where(
            ProjectResponsible.project_id == seed["project_id"]))).scalar_one()
        row.user_id = seed["engineer_id"]       # not in Sales: does not count
        await s.commit()
    c = await _create(client, pm, seed)
    assert c["sales_owner_id"] == bob
    async with session_factory() as s:
        row = (await s.execute(select(ProjectResponsible).where(
            ProjectResponsible.project_id == seed["project_id"]))).scalar_one()
        row.user_id = sally
        await s.commit()
    c = await _create(client, pm, seed)
    assert c["sales_owner_id"] == sally


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
    """Project Management captures (migration 152): the kickoff is the
    lead's (D2); with no lead it is Project Management's. Sales' only row at
    capture is the Sales contact's "Supply the customer's facts" while they
    are missing; otherwise Sales has no kickoff row."""
    await _join(session_factory, seed["engineer_id"], depts["Sales"])
    async with session_factory() as s:
        s.add(ProjectResponsible(project_id=seed["project_id"],
                                 department_id=depts["Sales"],
                                 user_id=seed["engineer_id"]))
        await s.commit()
    eng = await login(client, "eng@test.io", admin=False)
    c = await _create(client, {**admin, ACTS: str(depts["Project Manager"])}, seed)
    assert c["sales_owner_id"] == seed["engineer_id"]

    async def kickoff(headers):
        return [t for t in (await client.get("/api/v1/changes/my-tasks",
                                             headers=headers)).json()
                if t["change_id"] == c["id"] and t["kind"] == "kickoff"]
    assert c["lead_id"] is None         # the project names no PM
    # NEGATIVE: no lead: Project Management picks one, Sales has no row
    assert await kickoff(eng) == []
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"lead_id": seed["admin_id"]}, headers=admin)
    assert res.status_code == 200, res.text
    # D2 (2026-10-19): the hand-over is the lead's; while the customer's
    # facts are missing the Sales contact's own row is "Supply the
    # customer's facts" (review 2026-10-19)
    mine = await kickoff(eng)
    assert mine and mine[0]["missing"]
    assert mine[0]["kind_label"] == "Supply the customer's facts"
    assert mine[0]["role"] == "main" and mine[0]["is_mine"]
    from tests.conftest import satisfy_capture_gate
    await satisfy_capture_gate(client, admin, c["id"])
    # nothing of the customer's owed: no Sales row (Sales does not hand over)
    assert await kickoff(eng) == []
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
