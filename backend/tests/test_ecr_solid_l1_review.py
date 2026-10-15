"""ECR-solid L1 review fixes (P3 / C10 / P4):

- an engineering lead cannot turn its internal change into a customer change
  (P3 "internal only" would be bypassed); Sales / PM / admin may;
- a PATCH that makes a change internal never leaves a Sales owner behind;
- a stale Sales owner (inactive, left Sales) or an admin acting as Sales owns
  nothing: the Sales rows fall back to all of Sales as main;
- Sales has no capture task or capture hop on an engineering-led internal
  change;
- a missing lead names its owner (Project Management);
- stage-state serves the one price rule (can_see_prices)."""
import pytest
import pytest_asyncio
from sqlalchemy import update

from app.models.change import ChangeRequest
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from tests.conftest import KEEP_LEAD_RULE, login

pytestmark = pytest.mark.asyncio
ACTS = "X-Acts-As-Department"


@pytest_asyncio.fixture
async def depts(session_factory, seed):
    ids = {}
    async with session_factory() as s:
        for i, (n, cust, internal) in enumerate((
                ("Sales", True, False), ("Project Manager", True, False),
                ("Development", False, True), ("Quality", False, False),
                ("Management", False, False))):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=cust, can_start_internal_change=internal)
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


async def _user(session_factory, seed, name, dept_id):
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=name.lower(),
                 email=f"{name.lower()}@test.io", full_name=name,
                 hashed_password="x", role="engineer", is_active=True)
        s.add(u); await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept_id))
        await s.commit()
        return u.id, u.email


def _body(seed, customer):
    return {"project_id": seed["project_id"], "title": "fix", "reason": "r",
            "change_type": "physical_part", "customer_relevant": customer}


async def _dev_internal(client, seed, depts, session_factory):
    await _join(session_factory, seed["engineer_id"], depts["Development"])
    eng = await login(client, "eng@test.io", admin=False)
    res = await client.post("/api/v1/changes", json=_body(seed, False),
                            headers={**eng, KEEP_LEAD_RULE: "1"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["lead_id"] == seed["engineer_id"]
    return eng, res.json()["id"]


async def test_engineering_lead_cannot_flip_to_customer(client, seed, depts,
                                                       session_factory, admin):
    eng, cid = await _dev_internal(client, seed, depts, session_factory)
    res = await client.patch(f"/api/v1/changes/{cid}",
                             json={"customer_relevant": True}, headers=eng)
    assert res.status_code == 403, res.text
    assert "customer change" in res.json()["detail"]
    # the way back stays open, and an admin may flip it
    res = await client.patch(f"/api/v1/changes/{cid}",
                             json={"customer_relevant": True}, headers=admin)
    assert res.status_code == 200, res.text
    assert res.json()["customer_relevant"] is True


async def test_internal_flip_drops_the_sales_owner(client, seed, depts,
                                                  session_factory, admin):
    sally, _ = await _user(session_factory, seed, "Sally", depts["Sales"])
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = (await client.post("/api/v1/changes", json=_body(seed, True), headers=pm)).json()
    await client.patch(f"/api/v1/changes/{c['id']}", json={"sales_owner_id": sally},
                       headers=admin)
    # internal flip resending the current owner: the owner is dropped anyway
    res = await client.patch(f"/api/v1/changes/{c['id']}", json={
        "customer_relevant": False, "sales_owner_id": sally}, headers=admin)
    assert res.status_code == 200, res.text
    assert res.json()["sales_owner_id"] is None
    other, _ = await _user(session_factory, seed, "Otto", depts["Sales"])
    await client.patch(f"/api/v1/changes/{c['id']}", json={
        "customer_relevant": True}, headers=admin)
    # internal flip naming a new owner: refused, nothing written
    res = await client.patch(f"/api/v1/changes/{c['id']}", json={
        "customer_relevant": False, "sales_owner_id": other}, headers=admin)
    assert res.status_code == 400
    assert "internal" in res.json()["detail"]
    # flip to customer and name the owner in one PATCH
    internal = (await client.post("/api/v1/changes", json=_body(seed, False),
                                  headers=pm)).json()
    res = await client.patch(f"/api/v1/changes/{internal['id']}", json={
        "customer_relevant": True, "sales_owner_id": other}, headers=admin)
    assert res.status_code == 200, res.text
    assert res.json()["sales_owner_id"] == other


async def test_sales_owner_error_names_the_owner(client, seed, depts, admin):
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = (await client.post("/api/v1/changes", json=_body(seed, True), headers=pm)).json()
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"sales_owner_id": 999999}, headers=admin)
    assert res.status_code == 400
    assert res.json()["detail"] == "Sales owner user not found"


async def test_acting_admin_is_no_sales_owner(client, seed, depts, admin):
    sales = {**admin, ACTS: str(depts["Sales"])}
    c = (await client.post("/api/v1/changes", json=_body(seed, True), headers=sales)).json()
    assert c["sales_owner_id"] is None


async def test_stale_owner_leaves_sales_rows_main(client, seed, depts,
                                                 session_factory, admin):
    sally, _ = await _user(session_factory, seed, "Sally", depts["Sales"])
    _, otto_mail = await _user(session_factory, seed, "Otto", depts["Sales"])
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = (await client.post("/api/v1/changes", json=_body(seed, True), headers=pm)).json()
    await client.patch(f"/api/v1/changes/{c['id']}", json={"sales_owner_id": sally},
                       headers=admin)
    otto = await login(client, otto_mail, admin=False)

    async def otto_row():
        rows = [t for t in (await client.get("/api/v1/changes/my-tasks",
                                             headers=otto)).json()
                if t["change_id"] == c["id"] and t["kind"] == "kickoff"]
        assert rows
        return rows[0]
    assert (await otto_row())["role"] == "backup"
    async with session_factory() as s:
        await s.execute(update(User).where(User.id == sally).values(is_active=False))
        await s.commit()
    row = await otto_row()
    assert row["role"] == "main" and row["main_name"] is None


async def test_sales_has_no_part_in_an_engineering_internal_change(
        client, seed, depts, session_factory, admin):
    _, cid = await _dev_internal(client, seed, depts, session_factory)
    _, sally_mail = await _user(session_factory, seed, "Sally", depts["Sales"])
    sally = await login(client, sally_mail, admin=False)
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sally)).json()
    assert not any(t["change_id"] == cid for t in tasks)
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=sally)).json()
    assert st["can_transition"]["scoping"] is False
    assert st["can_transition"]["rejected"] is False
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=sally)
    assert res.status_code == 403
    # Project Management (the run team) still has it
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=pm)).json()
    assert any(t["change_id"] == cid and t["kind"] == "kickoff" for t in tasks)


async def test_missing_lead_is_project_managements(client, seed, depts,
                                                   session_factory, admin):
    """A Sales customer change on a project without a PM: the wait names who
    fixes it, and Project Management's kickoff row is its own (main)."""
    _, sally_mail = await _user(session_factory, seed, "Sally", depts["Sales"])
    sally = await login(client, sally_mail, admin=False)
    c = (await client.post("/api/v1/changes", json=_body(seed, True),
                           headers={**sally, KEEP_LEAD_RULE: "1"})).json()
    assert c["lead_id"] is None
    st = (await client.get(f"/api/v1/changes/{c['id']}/stage-state",
                           headers=sally)).json()
    assert any(w["kind"] == "no_lead" and "Project Management" in w["text"]
               for w in st["waits"])
    _, pam_mail = await _user(session_factory, seed, "Pam", depts["Project Manager"])
    pam = await login(client, pam_mail, admin=False)
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=pam)).json()
            if t["change_id"] == c["id"] and t["kind"] == "kickoff"]
    assert rows and rows[0]["role"] == "main"
    assert "lead" in rows[0]["hint"]


@pytest.mark.parametrize("dept,sees", [("Management", True), ("Quality", False)])
async def test_stage_state_serves_the_price_rule(client, seed, depts, admin, dept, sees):
    c = (await client.post("/api/v1/changes", json=_body(seed, True),
                           headers={**admin, ACTS: str(depts["Project Manager"])})).json()
    st = (await client.get(f"/api/v1/changes/{c['id']}/stage-state",
                           headers={**admin, ACTS: str(depts[dept])})).json()
    assert st["can_see_prices"] is sees
