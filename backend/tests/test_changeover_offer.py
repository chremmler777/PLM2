"""The changeover offered to the customer (Christoph 2026-11-09).

"Not that complex. For now Sales just offers running change or customer
scraps; Logistics will have the task after quoting ... It's only to tie the
customer down on its decision."

Sales (PM, the change lead, admin) set running_change | customer_scrap with
optional parts left / changeover date / note, until the customer answered.
The bank build (Logistics, after acceptance) is untouched.
"""
import pytest

from app.models.workflow import Department, UserDepartment
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def roles(session_factory, seed):
    from app.models.entities import User
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        depts, users = {}, {}
        for name, starter in [("Logistics", False), ("Sales", True)]:
            d = Department(name=name, flow_type="action", is_active=True,
                           can_start_change=starter)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        for name, email in [("Logistics", "sched@test.io"),
                            ("Sales", "sales@test.io")]:
            u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                     email=email, full_name=name,
                     hashed_password=get_password_hash("role-secret-1"),
                     role="engineer", is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[name]))
            users[name] = u.id
        await s.commit()
        return users


async def _auth(client, name):
    return await login(client, {"Logistics": "sched@test.io",
                                "Sales": "sales@test.io"}[name], ENGINEER_PASSWORD)


async def _change(client, auth, seed, session_factory, status="quoting"):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Changeover change",
        "reason": "r", "change_type": "physical_part"}, headers=auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status = status
        c.customer_relevant = True
        await s.commit()
    return cid


async def _put(client, cid, auth, **body):
    return await client.put(f"/api/v1/changes/{cid}/changeover-offer",
                            json=body, headers=auth)


async def test_sales_offers_running_change_with_details(client, admin_auth, seed,
                                                       roles, session_factory):
    sales = await _auth(client, "Sales")
    cid = await _change(client, admin_auth, seed, session_factory)
    res = await _put(client, cid, sales, mode="running_change",
                     old_stock_parts=1200, changeover_date="2026-12-18",
                     note="customer buys the old parts")
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["changeover_offer_mode"] == "running_change"
    assert b["old_stock_parts"] == 1200
    assert b["changeover_date"] == "2026-12-18"
    assert b["changeover_offer_note"] == "customer buys the old parts"
    assert b["changeover_offer_set_by_name"] == "Sales"
    assert b["changeover_offer_set_at"] is not None
    # Logistics' bank build is untouched (its task stays after acceptance)
    assert b["bank_build_mode"] is None and b["scrap_quote_price"] is None
    log = (await client.get(f"/api/v1/changes/{cid}/changelog",
                            headers=admin_auth)).json()
    assert any(r["action"] == "changeover_offered"
               and "1200 parts left" in r["action_description"] for r in log)


async def test_customer_scraps_with_nothing_else(client, admin_auth, seed, roles,
                                                 session_factory):
    sales = await _auth(client, "Sales")
    cid = await _change(client, admin_auth, seed, session_factory, status="costing")
    await _put(client, cid, sales, mode="running_change", old_stock_parts=5,
               changeover_date="2026-12-01")
    res = await _put(client, cid, sales, mode="customer_scrap")
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["changeover_offer_mode"] == "customer_scrap"
    # re-setting replaces the details
    assert b["old_stock_parts"] is None and b["changeover_date"] is None


async def test_refusals(client, admin_auth, seed, roles, session_factory):
    sales = await _auth(client, "Sales")
    logi = await _auth(client, "Logistics")
    cid = await _change(client, admin_auth, seed, session_factory)
    assert (await _put(client, cid, logi, mode="running_change")).status_code == 403
    assert (await _put(client, cid, sales, mode="planned_scrap")).status_code == 400
    assert (await _put(client, cid, sales, mode="running_change",
                       old_stock_parts=-1)).status_code == 400
    done = await _change(client, admin_auth, seed, session_factory, status="approved")
    res = await _put(client, done, sales, mode="running_change")
    assert res.status_code == 400 and "approved" in res.json()["detail"]
