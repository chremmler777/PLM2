"""ECR-solid spec §4 costing positions (C25, switch ASSESSMENT_V2).

Every external number stands on something: a quoted position finalizes only
with its offer's quote number and the quote file; an estimated one names its
reference (earlier tool, supplier figure + date) or 'same as' a part and
what differs. A quote that arrives after an offer or approval on the
estimate is compared with it: within +5 % / above by x; above opens the
price again and gives Sales (or the approver and lead) one task.
"""
import json
from datetime import datetime

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
        u = User(organization_id=seed["org_id"], username=f"cb-{key}",
                 email=f"cb-{key}@test.io", full_name=f"CB {key}",
                 hashed_password=get_password_hash("cb-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept_id = (await make_department_member(session_factory, uid, dept)
               if dept else None)
    return uid, dept_id, await login(client, f"cb-{key}@test.io")


@pytest.fixture
async def cb(client, session_factory, seed):
    _, tool, te = await _user(client, session_factory, seed, "te", "Tool Engineer")
    _, proc, pe = await _user(client, session_factory, seed, "pe", "Process Engineer")
    sales_id, _, sa = await _user(client, session_factory, seed, "sales", "Sales")
    async with session_factory() as s:
        project = await s.get(Project, seed["project_id"])
        s.add(DepartmentRate(department_id=tool, plant_id=project.plant_id,
                             hourly_rate=65.0, min_factor=1.0))
        change = ChangeRequest(
            change_number="C-CB-1", title="basis", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="costing",
            customer_relevant=True, sales_owner_id=sales_id)
        s.add(change)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id, department_id=tool, stage_order=1,
                               rasic_letter="R", status="submitted", verdict="feasible",
                               details=json.dumps(IMPACTED),
                               submitted_at=datetime.utcnow()))
        await s.commit()
        cid = change.id
    return {"cid": cid, "tool": tool, "te": te, "pe": pe, "sa": sa, "sales_id": sales_id}


def _u(cb, tail):
    return f"/api/v1/changes/{cb['cid']}{tail}"


async def _pos(client, cb, **body):
    res = await client.post(_u(cb, "/costing/positions"), json={
        "department_id": cb["tool"], "label": "Insert re-cut", "kind": "external",
        "quantity": 1, "quantity_unit": "pcs", **body}, headers=cb["te"])
    assert res.status_code == 201, res.text
    return res.json()


async def _finalize(client, cb):
    return await client.post(_u(cb, f"/costing/departments/{cb['tool']}/finalize"),
                             headers=cb["te"])


async def _offer(client, cb, pid, **body):
    res = await client.post(_u(cb, f"/costing/positions/{pid}/offers"), json={
        "vendor_name": "FZ", "cost": 1300.0, **body}, headers=cb["te"])
    assert res.status_code == 201, res.text
    return res.json()


async def _file(client, cb, oid):
    res = await client.post(_u(cb, "/attachments"),
                            files={"file": ("quote.pdf", b"%PDF-1.4 q", "application/pdf")},
                            data={"kind": "vendor_quote", "costing_offer_id": str(oid)},
                            headers=cb["te"])
    assert res.status_code in (200, 201), res.text


async def test_an_estimate_names_its_basis(client, cb):
    p = await _pos(client, cb, est_cost=900.0)
    assert p["basis"] == "estimate" and p["estimated"] is True
    res = await _finalize(client, cb)
    assert res.status_code == 400 and "Estimated positions need their basis" in res.text
    # negative: a reference that says nothing
    await client.put(_u(cb, f"/costing/positions/{p['id']}"),
                     json={"basis_ref": "ok"}, headers=cb["te"])
    assert (await _finalize(client, cb)).status_code == 400
    await client.put(_u(cb, f"/costing/positions/{p['id']}"),
                     json={"basis_ref": "Hasco figure 12 Oct 2026"}, headers=cb["te"])
    res = await _finalize(client, cb)
    assert res.status_code == 200, res.text


async def test_same_as_needs_the_part_and_what_differs(client, cb, session_factory, seed):
    from app.models.part import Part
    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="T-3454",
                    name="Tool 3454", part_type="internal_mfg",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.commit()
        part_id = part.id
    p = await _pos(client, cb, est_cost=900.0, basis="same_as", basis_part_id=part_id)
    assert p["basis_part_number"] == "T-3454"
    assert (await _finalize(client, cb)).status_code == 400
    await client.put(_u(cb, f"/costing/positions/{p['id']}"), json={
        "basis": "same_as", "basis_part_id": part_id,
        "basis_differs": "2 cavities instead of 4"}, headers=cb["te"])
    assert (await _finalize(client, cb)).status_code == 200


async def test_a_quote_finalizes_only_with_its_number_and_file(client, cb):
    p = await _pos(client, cb, pricing="quote")
    assert p["basis"] == "quote"
    res = await _finalize(client, cb)
    assert res.status_code == 400 and "no offer" in res.text
    o = await _offer(client, cb, p["id"])
    res = await _finalize(client, cb)
    assert res.status_code == 400 and "FZ: quote number and file" in res.text
    await client.put(_u(cb, f"/costing/offers/{o['id']}"),
                     json={"quote_ref": "FZ-Q-2231", "quoted_on": "2026-10-12",
                           "valid_until": "2026-12-31"}, headers=cb["te"])
    assert (await _finalize(client, cb)).status_code == 400      # no file yet
    await _file(client, cb, o["id"])
    res = await _finalize(client, cb)
    assert res.status_code == 200, res.text


async def test_quote_after_the_offer_is_compared_with_the_estimate(
        client, cb, session_factory):
    p = await _pos(client, cb, est_cost=1000.0, basis_ref="Hasco figure 12 Oct 2026")
    async with session_factory() as s:      # an offer went to the customer
        c = await s.get(ChangeRequest, cb["cid"])
        c.quoted_at = datetime.utcnow()
        await s.commit()
    await _offer(client, cb, p["id"], quote_ref="FZ-Q-2231")
    rows = (await client.get(_u(cb, "/costing/positions"), headers=cb["te"])).json()
    row = next(r for r in rows if r["id"] == p["id"])
    assert row["estimate_check"] == "pending"
    res = await _finalize(client, cb)
    assert res.status_code == 400 and "Compare the quote with your estimate" in res.text
    url = _u(cb, f"/costing/positions/{p['id']}/estimate-check")
    # negative: another department; above without the amount; no pick
    assert (await client.post(url, json={"verdict": "above", "over": 300},
                              headers=cb["pe"])).status_code == 403
    assert (await client.post(url, json={"verdict": "above"},
                              headers=cb["te"])).status_code == 400
    assert (await client.post(url, json={"verdict": "maybe"},
                              headers=cb["te"])).status_code == 400
    res = await client.post(url, json={"verdict": "above", "over": 300}, headers=cb["te"])
    assert res.status_code == 200, res.text
    assert res.json()["estimate_check"] == "above"
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cb["cid"])).price_open is True
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"estimate_low:{p['id']}"))).scalars().all()
        assert told == [cb["sales_id"]]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=cb["sa"])).json()
    assert any(t["kind"] == "estimate_low" and t["change_id"] == cb["cid"]
               and "300.00" in t["hint"] for t in tasks)
    # twice is refused: it was answered
    assert (await client.post(url, json={"verdict": "within"},
                              headers=cb["te"])).status_code == 400


async def test_switch_off_finalizes_without_a_basis(client, cb, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    await _pos(client, cb, est_cost=900.0)
    assert (await _finalize(client, cb)).status_code == 200


async def test_a_money_line_says_how_many_of_what(client, cb):
    """A3-07 (spec §4 [R3] 'Each: quantity + unit + basis pick'): a new
    money line names its quantity and unit; an edit cannot take them away;
    hours lines carry theirs (hours x rate)."""
    base = {"department_id": cb["tool"], "label": "Insert re-cut", "kind": "external",
            "est_cost": 4100.0, "basis_ref": "Tool 3343 recut 2025, FZ 4.1k"}
    for extra in ({}, {"quantity": 2}, {"quantity_unit": "inserts"}):
        res = await client.post(_u(cb, "/costing/positions"), json={**base, **extra},
                                headers=cb["te"])
        assert res.status_code == 400 and "how many of what" in res.json()["detail"], res.text
    res = await client.post(_u(cb, "/costing/positions"),
                            json={**base, "quantity": 2, "quantity_unit": "inserts"},
                            headers=cb["te"])
    assert res.status_code == 201, res.text
    assert (res.json()["quantity"], res.json()["quantity_unit"]) == (2, "inserts")
    pid = res.json()["id"]
    res = await client.put(_u(cb, f"/costing/positions/{pid}"),
                           json={"quantity_unit": " "}, headers=cb["te"])
    assert res.status_code == 400, res.text
    res = await client.post(_u(cb, "/costing/positions"), json={
        "department_id": cb["tool"], "label": "Own time", "kind": "own_time",
        "hours": 3}, headers=cb["te"])
    assert res.status_code == 201, res.text
