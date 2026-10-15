"""ECR-solid lane L5 (assessment + costing) review fixes.

Each test is a negative or a dead-end the review found: My Tasks with an
open supplier wait, money on non-price readers, check items closed without
evidence, the our-team question on an internal change, the pending
quote-vs-estimate check, and the served rights flags.
"""
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import DepartmentRate
from app.models.entities import Project, User
from app.models.notification import Notification
from app.services import cm_switches
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio
IMPACTED = {"impacts": [{"key": "cycle_time", "answer": "yes", "impacted": True}]}


async def _user(client, session_factory, seed, key, dept=None):
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"l5-{key}",
                 email=f"l5-{key}@test.io", full_name=f"L5 {key}",
                 hashed_password=get_password_hash("l5-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept_id = (await make_department_member(session_factory, uid, dept)
               if dept else None)
    return uid, dept_id, await login(client, f"l5-{key}@test.io")


@pytest.fixture
async def cc(client, session_factory, seed):
    """A customer change in costing: Toolshop answered feasible with an
    impact and owes its costing input."""
    lead_id, _, lead = await _user(client, session_factory, seed, "lead", "Project Manager")
    dale_id, shop, dale = await _user(client, session_factory, seed, "dale", "Toolshop")
    async with session_factory() as s:
        project = await s.get(Project, seed["project_id"])
        s.add(DepartmentRate(department_id=shop, plant_id=project.plant_id,
                             hourly_rate=65.0, min_factor=1.0))
        change = ChangeRequest(
            change_number="C-L5-1", title="l5 costing", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=lead_id, status="costing",
            customer_relevant=True)
        s.add(change)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id, department_id=shop, stage_order=1,
                               rasic_letter="R", status="submitted",
                               verdict="feasible", details=json.dumps(IMPACTED),
                               submitted_at=datetime.utcnow()))
        await s.commit()
        cid = change.id
    return {"cid": cid, "shop": shop, "dale": dale, "dale_id": dale_id,
            "lead": lead, "lead_id": lead_id}


def _u(cid, tail=""):
    return f"/api/v1/changes/{cid}{tail}"


async def _wait(client, cid, auth, dept, **extra):
    today = date.today()
    body = {"department_id": dept, "vendor_name": "FZ",
            "asked_on": (today - timedelta(days=8)).isoformat(),
            "expected_by": (today + timedelta(days=12)).isoformat(), **extra}
    return await client.post(_u(cid, "/supplier-waits"), json=body, headers=auth)


# --- C18: My Tasks with an open supplier wait --------------------------------

async def test_my_tasks_with_a_wait_after_a_scoping_change(
        client, cc, seed, session_factory):
    """The wait hint must not depend on which other changes the list holds:
    a scoping change listed BEFORE the waiting one used to rebind the name
    the hint is built with (AttributeError, My Tasks 500)."""
    from app.services.change_service import ChangeService
    assert (await _wait(client, cc["cid"], cc["dale"], cc["shop"])).status_code == 200
    async with session_factory() as s:
        scoping = ChangeRequest(
            change_number="C-L5-S", title="in scoping", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=cc["dale_id"], lead_id=cc["dale_id"], status="scoping",
            customer_relevant=True)
        s.add(scoping)
        await s.commit()
        sid = scoping.id
    async with session_factory() as s:
        user = await s.get(User, cc["dale_id"])
        first = await s.get(ChangeRequest, sid)
        waiting = await s.get(ChangeRequest, cc["cid"])
        rows = await ChangeService.stage_tasks(s, user, [first, waiting], {cc["shop"]})
    row = next(r for r in rows if r["kind"] == "costing_input")
    assert row["waiting_on"] == "FZ" and "FZ" in row["hint"]
    res = await client.get("/api/v1/changes/my-tasks", headers=cc["dale"])
    assert res.status_code == 200, res.text


# --- R23: money and position names on non-price readers ----------------------

async def _position(session_factory, cid, dept, by, label="Insert re-cut", **kw):
    from app.models.change_cost import CostingPosition
    async with session_factory() as s:
        p = CostingPosition(change_id=cid, department_id=dept, label=label,
                            kind="external", pricing="estimate", est_cost=5000.0,
                            basis="estimate", created_by=by, **kw)
        s.add(p)
        await s.commit()
        return p.id


async def test_quality_reads_no_saving_and_no_quote_vs_estimate_money(
        client, cc, seed, session_factory):
    _, _, quality = await _user(client, session_factory, seed, "q", "Quality")
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                          estimate_check="pending")
    async with session_factory() as s:      # an offer went to the customer
        (await s.get(ChangeRequest, cc["cid"])).quoted_at = datetime.utcnow()
        await s.commit()
    res = await client.post(_u(cc["cid"], f"/costing/positions/{pid}/estimate-check"),
                            json={"verdict": "above", "over": 4200}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cc["cid"])
        c.internal_saving = 12000.0
        c.internal_saving_basis = "calculated"
        await s.commit()
    # the price viewer reads both
    lead_view = (await client.get(_u(cc["cid"]), headers=cc["lead"])).json()
    assert lead_view["internal_saving"] == 12000.0
    log = (await client.get(_u(cc["cid"], "/changelog"), headers=cc["lead"])).json()
    row = next(r for r in log if r["action"] == "estimate_checked")
    assert "4200" in row["action_description"]
    # negative: Quality reads neither the saving nor the amount nor the label
    q_view = (await client.get(_u(cc["cid"]), headers=quality)).json()
    assert q_view["internal_saving"] is None
    log = (await client.get(_u(cc["cid"], "/changelog"), headers=quality)).json()
    row = next(r for r in log if r["action"] == "estimate_checked")
    assert "4200" not in json.dumps(row) and "Insert re-cut" not in json.dumps(row)
    # the owning department still reads its own position's verdict
    log = (await client.get(_u(cc["cid"], "/changelog"), headers=cc["dale"])).json()
    row = next(r for r in log if r["action"] == "estimate_checked")
    assert "Insert re-cut" in row["action_description"]
    assert "4200" not in row["action_description"]


async def test_estimate_checked_text_keeps_the_verdict():
    from app.services.price_redaction import redact_changelog_text, redact_value
    desc, _ = redact_changelog_text(
        "estimate_checked", "Quote vs estimate on 'Insert': above by 4200.00", None)
    assert desc == "Quote vs estimate on 'Insert': above"
    assert redact_value({"position_id": 1, "verdict": "above", "over": 4200.0},
                        "estimate_checked")["over"] is None


# --- C25: quote vs estimate after the offer or approval ----------------------

async def _set(session_factory, cid, **fields):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        for k, v in fields.items():
            setattr(c, k, v)
        await s.commit()


async def test_pm_enters_the_quote_after_the_offer_and_the_department_is_asked(
        client, cc, seed, session_factory):
    """R5/R18: in quoted status the department has no costing window; the
    pending check is its task, it is told once, and it can answer."""
    _, _, quality = await _user(client, session_factory, seed, "q2", "Quality")
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"])
    await _set(session_factory, cc["cid"], status="quoted", quoted_at=datetime.utcnow())
    res = await client.post(_u(cc["cid"], f"/costing/positions/{pid}/offers"), json={
        "vendor_name": "FZ", "cost": 5100.0, "quote_ref": "FZ-Q-2231"},
        headers=cc["lead"])
    assert res.status_code == 201, res.text
    async with session_factory() as s:
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"estimate_check:{pid}"))).scalars().all()
        assert told == [cc["dale_id"]]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=cc["dale"])).json()
    row = next(t for t in tasks if t["kind"] == "estimate_check")
    assert row["change_id"] == cc["cid"] and row["target_tab"] == "costing"
    assert row["kind_label"] == "Quote vs your estimate"
    rows = (await client.get(_u(cc["cid"], "/costing/positions"), headers=cc["dale"])).json()
    assert next(r for r in rows if r["id"] == pid)["can_check_estimate"] is True
    # negative: Quality is served no form and may not answer
    rows = (await client.get(_u(cc["cid"], "/costing/positions"), headers=quality)).json()
    assert all(not r["can_check_estimate"] for r in rows)
    url = _u(cc["cid"], f"/costing/positions/{pid}/estimate-check")
    assert (await client.post(url, json={"verdict": "within"},
                              headers=quality)).status_code == 403
    res = await client.post(url, json={"verdict": "within"}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=cc["dale"])).json()
    assert not [t for t in tasks if t["kind"] == "estimate_check"]


async def test_the_department_records_the_quote_and_compares_in_one_step(
        client, cc, seed, session_factory):
    """After approval, no Sales owner: the department records the quote that
    came in with its number, says 'above by x'; all of Sales is told."""
    sales_id, _, sales = await _user(client, session_factory, seed, "sa", "Sales")
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"])
    await _set(session_factory, cc["cid"], status="approved",
               quoted_at=datetime.utcnow(), sales_owner_id=None)
    rows = (await client.get(_u(cc["cid"], "/costing/positions"), headers=cc["dale"])).json()
    assert next(r for r in rows if r["id"] == pid)["can_check_estimate"] is True
    url = _u(cc["cid"], f"/costing/positions/{pid}/estimate-check")
    # negative: no supplier, a quote number that says nothing
    res = await client.post(url, json={"verdict": "above", "over": 4200}, headers=cc["dale"])
    assert res.status_code == 400 and "supplier" in res.json()["detail"]
    res = await client.post(url, json={"verdict": "above", "over": 4200,
                                       "vendor_name": "FZ", "quote_ref": "ok",
                                       "cost": 9200}, headers=cc["dale"])
    assert res.status_code == 400 and "quote number" in res.json()["detail"]
    res = await client.post(url, json={"verdict": "above", "over": 4200,
                                       "vendor_name": "FZ", "quote_ref": "FZ-Q-2240",
                                       "cost": 9200}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["estimate_check"] == "above"
    assert [o["quote_ref"] for o in body["offers"]] == ["FZ-Q-2240"]
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cc["cid"])).price_open is True
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"estimate_low:{pid}"))).scalars().all()
        assert told == [sales_id]
        # the department entered it itself: no "asked" notice to it
        asked = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"estimate_check:{pid}"))).scalars().all()
        assert asked == []
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    assert any(t["kind"] == "estimate_low" for t in tasks)
    # settled (Absorb or acceptance): a later open price brings no old task
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cc["cid"])
        await ChangeService._settle_estimate_checks(s, c)
        c.price_open = True          # e.g. a scope change after approval
        await s.commit()
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    assert not [t for t in tasks if t["kind"] == "estimate_low"]
    # negative: answered once, closed
    rows = (await client.get(_u(cc["cid"], "/costing/positions"), headers=cc["dale"])).json()
    assert next(r for r in rows if r["id"] == pid)["can_check_estimate"] is False


async def test_internal_wording_offers_absorb_only(client, cc, seed, session_factory):
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                          estimate_check="pending")
    await _set(session_factory, cc["cid"], customer_relevant=False, status="approved",
               internal_approved_at=datetime.utcnow())
    res = await client.post(_u(cc["cid"], f"/costing/positions/{pid}/estimate-check"),
                            json={"verdict": "above", "over": 500}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        titles = (await s.execute(select(Notification.title).where(
            Notification.subject_key == f"estimate_low:{pid}"))).scalars().all()
        assert titles and all("re-approve" not in t and "absorb" in t for t in titles)
