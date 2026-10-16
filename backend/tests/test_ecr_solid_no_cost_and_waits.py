"""ECR-solid spec §4 / §5 (switch ASSESSMENT_V2): "<Dept> has no cost" (C18)
and waiting on a supplier (one state everywhere).

- No cost: no work / absorbed (hours, 0 refused) / the supplier does it;
  finalizes the department's costing; refused while it has a position, a
  priced line or an open supplier wait, naming the colleague.
- Supplier wait: vendor, asked on, expected by; holds the department's
  finalize; pauses its costing task's late clock (due at expected-by);
  close costing (C5) names it; the lead may "Price on estimate", the
  department is told.
"""
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import DepartmentRate
from app.models.entities import Project
from app.models.notification import Notification
from app.services import cm_switches
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio
IMPACTED = {"impacts": [{"key": "cycle_time", "answer": "yes", "impacted": True}]}


async def _user(client, session_factory, seed, key, dept=None):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"nc-{key}",
                 email=f"nc-{key}@test.io", full_name=f"NC {key}",
                 hashed_password=get_password_hash("nc-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept_id = (await make_department_member(session_factory, uid, dept)
               if dept else None)
    return uid, dept_id, await login(client, f"nc-{key}@test.io")


@pytest.fixture
async def ec(client, session_factory, seed):
    """A change in costing: Toolshop and Process both answered feasible
    with an impact and owe their costing input."""
    lead_id, _, lead = await _user(client, session_factory, seed, "lead", "Project Manager")
    dale_id, shop, dale = await _user(client, session_factory, seed, "dale", "Toolshop")
    _, proc, pe = await _user(client, session_factory, seed, "pe", "Process Engineer")
    async with session_factory() as s:
        project = await s.get(Project, seed["project_id"])
        for d in (shop, proc):
            s.add(DepartmentRate(department_id=d, plant_id=project.plant_id,
                                 hourly_rate=65.0, min_factor=1.0))
        change = ChangeRequest(
            change_number="C-NC-1", title="no cost", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=lead_id, status="costing",
            customer_relevant=True)
        s.add(change)
        await s.flush()
        for d in (shop, proc):
            s.add(ChangeAssessment(change_id=change.id, department_id=d, stage_order=1,
                                   rasic_letter="R", status="submitted",
                                   verdict="feasible", details=json.dumps(IMPACTED),
                                   submitted_at=datetime.utcnow()))
        await s.commit()
        cid = change.id
    return {"cid": cid, "shop": shop, "proc": proc, "dale": dale, "pe": pe,
            "lead": lead, "dale_id": dale_id, "lead_id": lead_id}


def _u(ec, tail):
    return f"/api/v1/changes/{ec['cid']}{tail}"


async def _no_cost(client, ec, dept, auth, **body):
    return await client.post(_u(ec, f"/costing/departments/{dept}/no-cost"),
                             json=body, headers=auth)


async def _wait(client, ec, auth, dept, **extra):
    today = date.today()
    body = {"department_id": dept, "vendor_name": "FZ",
            "asked_on": (today - timedelta(days=8)).isoformat(),
            "expected_by": (today + timedelta(days=12)).isoformat(), **extra}
    return await client.post(_u(ec, "/supplier-waits"), json=body, headers=auth)


# --- no cost ---------------------------------------------------------------

async def test_no_cost_finalizes_with_its_reason(client, ec):
    res = await _no_cost(client, ec, ec["shop"], ec["dale"], reason="absorbed")
    assert res.status_code == 400 and "hours" in res.json()["detail"]      # 0 refused
    res = await _no_cost(client, ec, ec["shop"], ec["dale"], reason="maybe")
    assert res.status_code == 400
    res = await _no_cost(client, ec, ec["shop"], ec["dale"], reason="absorbed", hours=6)
    assert res.status_code == 200, res.text
    assert ec["shop"] in res.json()["finalized_department_ids"]
    detail = (await client.get(_u(ec, ""), headers=ec["dale"])).json()
    assert detail["costing_no_cost"][str(ec["shop"])] == {"reason": "absorbed", "hours": 6.0}
    # reopening drops the "no cost" with the finalization
    res = await client.post(_u(ec, f"/costing/departments/{ec['shop']}/reopen"),
                            json={"reason": "toolmakers needed after all"},
                            headers=ec["dale"])
    assert res.status_code == 200, res.text
    detail = (await client.get(_u(ec, ""), headers=ec["dale"])).json()
    assert detail["costing_no_cost"] == {}


async def test_no_cost_refused_for_others_and_with_a_position(client, ec):
    # negative: Process may not say Toolshop has no cost
    res = await _no_cost(client, ec, ec["shop"], ec["pe"], reason="no_work")
    assert res.status_code == 403
    # negative: a position of the department, named with its author
    pos = await client.post(_u(ec, "/costing/positions"), json={
        "department_id": ec["shop"], "label": "Insert re-cut", "kind": "external", "quantity": 1, "quantity_unit": "pcs",
        "est_cost": 900.0}, headers=ec["dale"])
    assert pos.status_code == 201, pos.text
    res = await _no_cost(client, ec, ec["shop"], ec["dale"], reason="no_work")
    assert res.status_code == 400
    assert "NC dale has a cost position 'Insert re-cut'" in res.json()["detail"]


# --- supplier wait ---------------------------------------------------------

async def test_wait_holds_finalize_and_no_cost_and_names_itself(client, ec):
    res = await _wait(client, ec, ec["dale"], ec["shop"])
    assert res.status_code == 200, res.text
    w = res.json()[0]
    assert w["is_open"] and w["chip"] == "day 9 of 20"
    # negative: finalize and "no cost" wait for it
    await client.post(_u(ec, "/costing/positions"), json={
        "department_id": ec["shop"], "label": "Insert re-cut", "kind": "external", "quantity": 1, "quantity_unit": "pcs",
        "est_cost": 900.0}, headers=ec["dale"])
    res = await client.post(_u(ec, f"/costing/departments/{ec['shop']}/finalize"),
                            headers=ec["dale"])
    assert res.status_code == 400 and "Waiting on FZ until" in res.json()["detail"]
    res = await _no_cost(client, ec, ec["proc"], ec["pe"], reason="no_work")
    assert res.status_code == 200, res.text      # Process is not waiting
    # close costing names the wait (C5)
    blocked = await client.post(_u(ec, "/transition"), json={"to_status": "quoting"},
                                headers=ec["lead"])
    assert blocked.status_code in (400, 409), blocked.text
    assert "Waiting on FZ until" in blocked.text
    # the header serves it
    detail = (await client.get(_u(ec, ""), headers=ec["dale"])).json()
    assert [x["vendor_name"] for x in detail["open_supplier_waits"]] == ["FZ"]


async def test_wait_pauses_the_costing_task(client, ec):
    await _wait(client, ec, ec["dale"], ec["shop"])
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=ec["dale"])).json()
    row = next(t for t in tasks if t["kind"] == "costing_input"
               and t["change_id"] == ec["cid"])
    assert row["waiting_on"] == "FZ"
    assert row["due_date"][:10] >= (date.today() + timedelta(days=12)).isoformat()
    assert row["late"] is False


async def test_wait_rights_and_dates(client, ec):
    # negative: another department records no wait for Toolshop
    res = await _wait(client, ec, ec["pe"], ec["shop"])
    assert res.status_code == 403
    # negative: expected before asked, expected in the past
    today = date.today()
    res = await _wait(client, ec, ec["dale"], ec["shop"],
                      expected_by=(today - timedelta(days=9)).isoformat())
    assert res.status_code == 400
    res = await _wait(client, ec, ec["dale"], ec["shop"],
                      expected_by=(today - timedelta(days=1)).isoformat())
    assert res.status_code == 400 and "past" in res.json()["detail"]
    assert (await _wait(client, ec, ec["dale"], ec["shop"])).status_code == 200
    # negative: the same vendor twice
    res = await _wait(client, ec, ec["dale"], ec["shop"])
    assert res.status_code == 400 and "Already waiting" in res.json()["detail"]


async def test_lead_prices_on_estimate_and_the_department_is_told(
        client, ec, session_factory):
    wid = (await _wait(client, ec, ec["dale"], ec["shop"])).json()[0]["id"]
    url = _u(ec, f"/supplier-waits/{wid}/close")
    # negative: the department does not decide to price on its estimate
    res = await client.post(url, json={"reason": "price_on_estimate"}, headers=ec["dale"])
    assert res.status_code == 403
    res = await client.post(url, json={"reason": "price_on_estimate"}, headers=ec["lead"])
    assert res.status_code == 200, res.text
    assert res.json()[0]["close_reason"] == "price_on_estimate"
    async with session_factory() as s:
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"wait:{wid}:estimate"))).scalars().all()
        assert told == [ec["dale_id"]]
    # negative: closed twice
    res = await client.post(url, json={"reason": "received"}, headers=ec["dale"])
    assert res.status_code == 400


async def test_switch_off(client, ec, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    assert (await _wait(client, ec, ec["dale"], ec["shop"])).status_code == 400
    res = await _no_cost(client, ec, ec["shop"], ec["dale"], reason="no_work")
    assert res.status_code == 400
