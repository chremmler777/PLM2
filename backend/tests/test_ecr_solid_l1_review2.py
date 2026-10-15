"""ECR-solid L1 review, loop 2:

- Sales and Project Management turn an engineering-led internal change into a
  customer change without leading it; the engineering lead and a lead from a
  non-starter department are refused (P3 / C10);
- Management reads every costing and implementation position, as the price
  rule says (P4: one price rule);
- Management and retired departments are never routed (P4);
- an admin acting as Development who raises an internal change is not made
  its lead (P3 / C32);
- a retired department grants nothing: its members own nothing (R25);
- a hold needs a reason and leaves the run team a "resume or cancel" task;
- Project Management sees the kickoff of an internal change with a lead as
  backup, with the lead's name;
- a non-starter hears who starts what; a Sales or PM raiser who omits
  customer_relevant raises a customer change."""
import pytest
import pytest_asyncio
from sqlalchemy import update

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
                ("Management", False, False), ("Process Engineer", False, True))):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=cust, can_start_internal_change=internal)
            s.add(d); await s.flush(); ids[n] = d.id
        await s.commit()
    return ids


@pytest_asyncio.fixture
async def admin(client):
    return await login(client, "admin@test.io")


async def _user(session_factory, seed, name, dept_id):
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=name.lower(),
                 email=f"{name.lower()}@test.io", full_name=name,
                 hashed_password="x", role="engineer", is_active=True)
        s.add(u); await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept_id))
        await s.commit()
        return u.id, u.email


def _body(seed, customer=None):
    b = {"project_id": seed["project_id"], "title": "fix", "reason": "r",
         "change_type": "physical_part"}
    if customer is not None:
        b["customer_relevant"] = customer
    return b


async def _dev_internal(client, seed, depts, session_factory):
    """An internal change raised (and so led) by a Development member."""
    _, mail = await _user(session_factory, seed, "Devon", depts["Development"])
    dev = await login(client, mail, admin=False)
    res = await client.post("/api/v1/changes", json=_body(seed, False),
                            headers={**dev, KEEP_LEAD_RULE: "1"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["lead_id"] is not None
    return dev, res.json()


# --- P3 / C10: the customer flip --------------------------------------------

@pytest.mark.parametrize("dept", ["Sales", "Project Manager"])
async def test_sales_and_pm_flip_an_engineering_internal_change(
        client, seed, depts, session_factory, admin, dept):
    _, c = await _dev_internal(client, seed, depts, session_factory)
    _, mail = await _user(session_factory, seed, "Flipper", depts[dept])
    who = await login(client, mail, admin=False)
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"customer_relevant": True}, headers=who)
    assert res.status_code == 200, res.text
    assert res.json()["customer_relevant"] is True
    # the way back stays the lead's: Sales / PM who do not lead it may not
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"customer_relevant": False}, headers=who)
    assert res.status_code == 403
    assert "change lead" in res.json()["detail"]


async def test_engineering_lead_hears_who_flips(client, seed, depts,
                                               session_factory):
    dev, c = await _dev_internal(client, seed, depts, session_factory)
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"customer_relevant": True}, headers=dev)
    assert res.status_code == 403
    assert res.json()["detail"] == ("Only Sales, Project Management or an "
                                    "admin may make this a customer change")


async def test_quality_lead_cannot_flip(client, seed, depts, session_factory, admin):
    qid, qmail = await _user(session_factory, seed, "Quinn", depts["Quality"])
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = (await client.post("/api/v1/changes", json=_body(seed, False),
                           headers=pm)).json()
    res = await client.patch(f"/api/v1/changes/{c['id']}", json={"lead_id": qid},
                             headers=pm)
    assert res.status_code == 200, res.text
    q = await login(client, qmail, admin=False)
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"customer_relevant": True}, headers=q)
    assert res.status_code == 403
    assert "Sales, Project Management" in res.json()["detail"]


# --- P4: one price rule, Management included --------------------------------

@pytest.mark.parametrize("dept,all_rows", [("Management", True), ("Quality", False)])
async def test_management_reads_every_position(client, seed, depts, session_factory,
                                               admin, dept, all_rows):
    from app.models.change import ChangeRequest
    from app.services.costing_position_service import CostingPositionService
    from app.services.implementation_service import ImplementationService
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = (await client.post("/api/v1/changes", json=_body(seed, True), headers=pm)).json()
    uid, _ = await _user(session_factory, seed, "Viewer", depts[dept])
    async with session_factory() as s:
        change = await s.get(ChangeRequest, c["id"])
        user = await s.get(User, uid)
        for svc in (CostingPositionService, ImplementationService):
            got = await svc.readable_department_ids(s, change, user)
            assert (got is None) is all_rows, (svc.__name__, got)
    res = await client.get(f"/api/v1/changes/{c['id']}/costing/positions",
                           headers=await login(client, "viewer@test.io", admin=False))
    assert res.status_code == 200, res.text


# --- P4: Management and retired departments are never routed ---------------

async def test_management_and_retired_departments_are_never_routed(
        client, seed, depts, session_factory, admin):
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = (await client.post("/api/v1/changes", json=_body(seed, True), headers=pm)).json()
    url = f"/api/v1/changes/{c['id']}/routing/deviation"
    body = {"op": "add", "rasic_letter": "R", "reason": "need them"}
    res = await client.post(url, json={**body, "department_id": depts["Management"]},
                            headers=admin)
    assert res.status_code == 400
    assert "never routed" in res.json()["detail"]
    # a Management member adding itself: the same answer
    _, mail = await _user(session_factory, seed, "Boss", depts["Management"])
    boss = await login(client, mail, admin=False)
    res = await client.post(url, json={**body, "department_id": depts["Management"]},
                            headers=boss)
    assert res.status_code == 400
    async with session_factory() as s:
        await s.execute(update(Department).where(Department.id == depts["Quality"])
                        .values(is_active=False))
        await s.commit()
    res = await client.post(url, json={**body, "department_id": depts["Quality"]},
                            headers=admin)
    assert res.status_code == 400
    assert "retired" in res.json()["detail"]


# --- P3 / C32: an acting admin is no raiser-lead -----------------------------

async def test_acting_admin_raiser_is_not_the_lead(client, seed, depts, admin):
    dev = {**admin, ACTS: str(depts["Development"]), KEEP_LEAD_RULE: "1"}
    res = await client.post("/api/v1/changes", json=_body(seed, False), headers=dev)
    assert res.status_code in (200, 201), res.text
    # no project PM in the seed: nobody leads, Project Management picks one
    assert res.json()["lead_id"] is None


# --- R25: a retired department grants nothing --------------------------------

async def test_retired_sales_owns_nothing(client, seed, depts, session_factory, admin):
    from app.services.project_team_service import is_live_member
    sally, _ = await _user(session_factory, seed, "Sally", depts["Sales"])
    pm = {**admin, ACTS: str(depts["Project Manager"])}
    c = (await client.post("/api/v1/changes", json=_body(seed, True), headers=pm)).json()
    async with session_factory() as s:
        await s.execute(update(Department).where(Department.id == depts["Sales"])
                        .values(is_active=False))
        await s.commit()
        assert await is_live_member(s, sally, "Sales") is False
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"sales_owner_id": sally}, headers=admin)
    assert res.status_code == 400
    res = await client.get(f"/api/v1/changes/{c['id']}/sales-owner-candidates",
                           headers=admin)
    assert res.status_code == 200 and res.json() == []


# --- C1 hold: a reason, and a task for the run team ---------------------------

async def _rows(client, headers, cid, kind):
    return [t for t in (await client.get("/api/v1/changes/my-tasks",
                                         headers=headers)).json()
            if t["change_id"] == cid and t["kind"] == kind]


async def test_hold_needs_a_reason_and_leaves_a_resume_task(
        client, seed, depts, session_factory, monkeypatch):
    dev, c = await _dev_internal(client, seed, depts, session_factory)
    url = f"/api/v1/changes/{c['id']}/transition"
    res = await client.post(url, json={"to_status": "on_hold"}, headers=dev)
    assert res.status_code == 400
    assert "on hold" in res.json()["detail"]
    res = await client.post(url, json={"to_status": "on_hold",
                                       "reason": "waiting for the tool trial"},
                            headers=dev)
    assert res.status_code == 200, res.text
    rows = await _rows(client, dev, c["id"], "hold_resume")
    assert len(rows) == 1
    assert rows[0]["role"] == "main"
    assert rows[0]["reason"] == "waiting for the tool trial"
    # Project Management backs the lead up, with the lead's name
    _, pam_mail = await _user(session_factory, seed, "Pam", depts["Project Manager"])
    pam = await login(client, pam_mail, admin=False)
    rows = await _rows(client, pam, c["id"], "hold_resume")
    assert rows and rows[0]["role"] == "backup" and rows[0]["main_name"] == "Devon"
    # nobody else owns the resume
    _, sally_mail = await _user(session_factory, seed, "Sally", depts["Sales"])
    sally = await login(client, sally_mail, admin=False)
    assert await _rows(client, sally, c["id"], "hold_resume") == []
    # resume clears the task
    res = await client.post(url, json={"to_status": "captured"}, headers=dev)
    assert res.status_code == 200, res.text
    assert await _rows(client, dev, c["id"], "hold_resume") == []
    # switch off: the reason is optional again
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    res = await client.post(url, json={"to_status": "on_hold"}, headers=dev)
    assert res.status_code == 200, res.text


# --- R5/R18: kickoff of a led internal change: PM is backup ------------------

async def test_pm_backs_up_the_kickoff_of_a_led_internal_change(
        client, seed, depts, session_factory):
    dev, c = await _dev_internal(client, seed, depts, session_factory)
    rows = await _rows(client, dev, c["id"], "kickoff")
    assert rows and rows[0]["role"] == "main"
    _, pam_mail = await _user(session_factory, seed, "Pam", depts["Project Manager"])
    pam = await login(client, pam_mail, admin=False)
    rows = await _rows(client, pam, c["id"], "kickoff")
    assert rows and rows[0]["role"] == "backup"
    assert rows[0]["main_name"] == "Devon"


# --- P3: who starts what; the API default -------------------------------------

async def test_non_starter_hears_who_starts_what(client, seed, depts, session_factory):
    _, mail = await _user(session_factory, seed, "Quinn", depts["Quality"])
    q = await login(client, mail, admin=False)
    res = await client.post("/api/v1/changes", json=_body(seed, False), headers=q)
    assert res.status_code == 403
    detail = res.json()["detail"]
    assert "Sales, Project Manager" in detail and "customer" in detail
    assert "Development, Process Engineer" in detail and "internal" in detail


async def test_omitted_carrier_follows_the_raiser(client, seed, depts, session_factory):
    sid, smail = await _user(session_factory, seed, "Sally", depts["Sales"])
    sales = await login(client, smail, admin=False)
    res = await client.post("/api/v1/changes", json=_body(seed), headers=sales)
    assert res.status_code in (200, 201), res.text
    assert res.json()["customer_relevant"] is True
    assert res.json()["sales_owner_id"] == sid
    did, dmail = await _user(session_factory, seed, "Devon", depts["Development"])
    dev = await login(client, dmail, admin=False)
    res = await client.post("/api/v1/changes", json=_body(seed),
                            headers={**dev, KEEP_LEAD_RULE: "1"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["customer_relevant"] is False
    assert res.json()["lead_id"] == did
