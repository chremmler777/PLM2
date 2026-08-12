"""The scheduling block (stage 7): the bank-build decision and its publication.

After acceptance Scheduling says HOW the change reaches the line — running
change (consume the bank) or planned scrap (throw it away). Scrap is billed to
the customer, so it is only sayable with an additional scrap quote behind it.
Sales then publishes the plan to the customer. Neither act gates the transition
to in_implementation; both show up as my-tasks rows.
"""
import pytest

from app.models.workflow import Department, UserDepartment
from tests.conftest import login, lock_impact, approve_gates, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def roles(session_factory, seed):
    """Scheduling / Sales / a member of neither, each with its own user."""
    from app.models.entities import User
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        depts, users = {}, {}
        for name, starter in [("Scheduling", False), ("Sales", True)]:
            d = Department(name=name, flow_type="action", is_active=True,
                           can_start_change=starter)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        for name, email in [("Scheduling", "sched@test.io"),
                            ("Sales", "sales@test.io"),
                            ("Outsider", "outsider@test.io")]:
            u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                     email=email, full_name=name,
                     hashed_password=get_password_hash("role-secret-1"),
                     role="engineer", is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            if name in depts:
                s.add(UserDepartment(user_id=u.id, department_id=depts[name]))
            users[name] = u.id
        await s.commit()
        return {"dept": depts, "user": users}


async def _auth(client, name):
    return await login(client, {"Scheduling": "sched@test.io",
                                "Sales": "sales@test.io",
                                "Outsider": "outsider@test.io"}[name],
                       ENGINEER_PASSWORD)


async def _change(client, auth, seed, *, status="approved",
                  customer_relevant=True, session_factory=None):
    """A change parked directly at the target status — the scheduling block is
    what is under test, not the road to it."""
    # Always captured through the external flow (creating an internal change
    # outright is refused today); customer_relevant is flipped below with the
    # status, the same shortcut the internal-approval tests take.
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Bank build change",
        "reason": "r", "change_type": "physical_part"}, headers=auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status = status
        c.customer_relevant = customer_relevant
        await s.commit()
    return cid


async def _tasks(client, auth, kind=None):
    res = await client.get("/api/v1/changes/my-tasks", headers=auth)
    assert res.status_code == 200, res.text
    rows = res.json()
    return [t for t in rows if kind is None or t["kind"] == kind]


async def _actions(client, auth, cid):
    res = await client.get(f"/api/v1/changes/{cid}/changelog", headers=auth)
    assert res.status_code == 200, res.text
    return [e["action"] for e in res.json()]


async def test_scheduling_sets_running_change(client, admin_auth, seed, roles,
                                              session_factory):
    sched = await _auth(client, "Scheduling")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "running_change",
                                 "note": "run in at week 34"}, headers=sched)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bank_build_mode"] == "running_change"
    assert body["bank_build_note"] == "run in at week 34"
    assert body["scrap_quote_price"] is None
    assert body["bank_build_set_by"] == roles["user"]["Scheduling"]
    assert body["bank_build_set_by_name"] == "Scheduling"
    assert body["bank_build_set_at"] is not None
    assert body["plan_published_at"] is None
    assert "bank_build_decided" in await _actions(client, admin_auth, cid)


async def test_planned_scrap_needs_a_scrap_quote(client, admin_auth, seed, roles,
                                                 session_factory):
    sched = await _auth(client, "Scheduling")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "planned_scrap"}, headers=sched)
    assert res.status_code == 400, res.text
    # The refusal names the rule, not just the missing field.
    assert "customer bears the scrap cost" in res.json()["detail"]

    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "planned_scrap",
                                 "scrap_quote_price": 4200.50,
                                 "note": "scrap 1200 pcs"}, headers=sched)
    assert res.status_code == 200, res.text
    assert res.json()["bank_build_mode"] == "planned_scrap"
    assert res.json()["scrap_quote_price"] == 4200.50


async def test_zero_scrap_price_is_not_a_quote(client, admin_auth, seed, roles,
                                               session_factory):
    sched = await _auth(client, "Scheduling")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "planned_scrap",
                                 "scrap_quote_price": 0}, headers=sched)
    assert res.status_code == 422, res.text


async def test_redeciding_overwrites_and_running_change_clears_the_price(
        client, admin_auth, seed, roles, session_factory):
    sched = await _auth(client, "Scheduling")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "planned_scrap",
                                 "scrap_quote_price": 900}, headers=sched)
    assert res.status_code == 200, res.text
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "running_change"}, headers=sched)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bank_build_mode"] == "running_change"
    # The scrap price must never be readable alongside a running change.
    assert body["scrap_quote_price"] is None
    assert (await _actions(client, admin_auth, cid)).count("bank_build_decided") == 2


async def test_unknown_mode_is_refused(client, admin_auth, seed, roles,
                                       session_factory):
    sched = await _auth(client, "Scheduling")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "maybe_later"}, headers=sched)
    assert res.status_code == 400, res.text


async def test_non_member_is_refused(client, admin_auth, seed, roles,
                                     session_factory):
    outsider = await _auth(client, "Outsider")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "running_change"}, headers=outsider)
    assert res.status_code == 403, res.text
    # Sales owns the customer conversation, not the shop-floor plan.
    sales = await _auth(client, "Sales")
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "running_change"}, headers=sales)
    assert res.status_code == 403, res.text


async def test_wrong_status_is_refused(client, admin_auth, seed, roles,
                                       session_factory):
    sched = await _auth(client, "Scheduling")
    cid = await _change(client, admin_auth, seed, status="costing",
                        session_factory=session_factory)
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "running_change"}, headers=sched)
    assert res.status_code == 400, res.text
    assert "approved" in res.json()["detail"]
    # Admins fill things in after the fact and are exempt from the window.
    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "running_change"}, headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_publish_requires_a_decided_plan_and_is_sales_gated(
        client, admin_auth, seed, roles, session_factory):
    sched = await _auth(client, "Scheduling")
    sales = await _auth(client, "Sales")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)

    res = await client.post(f"/api/v1/changes/{cid}/bank-build/publish",
                            headers=sales)
    assert res.status_code == 400, res.text
    assert "before publishing" in res.json()["detail"]

    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "running_change"}, headers=sched)
    assert res.status_code == 200, res.text

    # Scheduling may not publish its own plan.
    res = await client.post(f"/api/v1/changes/{cid}/bank-build/publish",
                            headers=sched)
    assert res.status_code == 403, res.text

    res = await client.post(f"/api/v1/changes/{cid}/bank-build/publish",
                            headers=sales)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plan_published_by"] == roles["user"]["Sales"]
    assert body["plan_published_by_name"] == "Sales"
    first = body["plan_published_at"]
    assert first is not None
    assert "bank_build_published" in await _actions(client, admin_auth, cid)


async def test_republish_refreshes_the_stamp(client, admin_auth, seed, roles,
                                             session_factory):
    sched = await _auth(client, "Scheduling")
    sales = await _auth(client, "Sales")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)
    await client.put(f"/api/v1/changes/{cid}/bank-build",
                     json={"mode": "running_change"}, headers=sched)
    first = (await client.post(f"/api/v1/changes/{cid}/bank-build/publish",
                               headers=sales)).json()["plan_published_at"]
    assert first is not None
    # Backdate the stamp so the refresh is observable rather than a same-second
    # tie: what is under test is that republishing MOVES it, not that it errors.
    from datetime import datetime, timedelta
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.plan_published_at = datetime.utcnow() - timedelta(days=1)
        await s.commit()
    backdated = (await client.get(f"/api/v1/changes/{cid}",
                                  headers=sales)).json()["plan_published_at"]
    res = await client.post(f"/api/v1/changes/{cid}/bank-build/publish",
                            headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["plan_published_at"] > backdated
    assert (await _actions(client, admin_auth, cid)).count("bank_build_published") == 2


async def test_my_tasks_hands_the_change_from_scheduling_to_sales(
        client, admin_auth, seed, roles, session_factory):
    sched = await _auth(client, "Scheduling")
    sales = await _auth(client, "Sales")
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)

    rows = await _tasks(client, sched, "bank_build")
    assert [r["change_id"] for r in rows] == [cid]
    assert "running change" in rows[0]["hint"]
    assert await _tasks(client, sales, "publish_plan") == []

    res = await client.put(f"/api/v1/changes/{cid}/bank-build",
                           json={"mode": "planned_scrap",
                                 "scrap_quote_price": 1500}, headers=sched)
    assert res.status_code == 200, res.text

    # Decided: Scheduling's row is gone, Sales' publication row is up.
    assert await _tasks(client, sched, "bank_build") == []
    rows = await _tasks(client, sales, "publish_plan")
    assert [r["change_id"] for r in rows] == [cid]
    assert rows[0]["mode"] == "planned_scrap"
    assert rows[0]["scrap_quote_price"] == 1500.0

    res = await client.post(f"/api/v1/changes/{cid}/bank-build/publish",
                            headers=sales)
    assert res.status_code == 200, res.text
    assert await _tasks(client, sales, "publish_plan") == []


async def test_internal_change_owes_the_customer_no_plan(
        client, admin_auth, seed, roles, session_factory):
    sched = await _auth(client, "Scheduling")
    sales = await _auth(client, "Sales")
    cid = await _change(client, admin_auth, seed, customer_relevant=False,
                        session_factory=session_factory)
    # Scheduling still has to plan the build...
    assert [r["change_id"] for r in await _tasks(client, sched, "bank_build")] == [cid]
    await client.put(f"/api/v1/changes/{cid}/bank-build",
                     json={"mode": "running_change"}, headers=sched)
    # ...but there is no customer to publish it to.
    assert await _tasks(client, sales, "publish_plan") == []


async def test_approved_to_in_implementation_is_still_open(
        client, admin_auth, seed, roles, session_factory):
    """No hard gate tonight: an undecided bank build must not block the
    existing approved -> in_implementation flow."""
    cid = await _change(client, admin_auth, seed, session_factory=session_factory)
    await lock_impact(session_factory, cid, seed["admin_id"])
    await approve_gates(client, admin_auth, cid, "release")
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_implementation"},
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["bank_build_mode"] is None
