"""The change plan: quote plan seeded from costing, detailed plan confirmed by
every responsible team, 'Timing validated' as the baseline, deviations after
it, and the MS Project / CSV exports.

The rules pinned here: the template turns the costing into a real timeline;
the plan math (validation, critical path, forward pass) says what the spec
says; only the plan editors shape the plan and a department only reports
progress on its own blocks; a confirmation goes stale when the plan moves;
timing is validated only when every team confirmed a clean, idea-free plan;
after that a date moves only as a deviation with a reason.
"""
import csv
import io
import math
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import CostingOffer, CostingPosition
from app.models.change_plan import ChangePlanTask
from app.models.workflow import Department, UserDepartment
from app.services.change_plan_service import (
    critical_path, topo_order, validate_plan,
)
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio

NS = "{http://schemas.microsoft.com/project}"


@pytest.fixture
async def world(session_factory, seed):
    """Departments, one member each, and a customer-relevant change in
    costing with an impact lock and a Tool Engineer R assessment."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        depts = {}
        for name in ("Sales", "Project Manager", "Scheduling", "Tool Engineer",
                     "APQP", "Packaging Engineer"):
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for key, dept in (("sales", "Sales"), ("pm", "Project Manager"),
                          ("sched", "Scheduling"), ("tool", "Tool Engineer"),
                          ("apqp", "APQP"), ("pack", "Packaging Engineer")):
            email = f"plan-{key}@test.io"
            u = User(organization_id=seed["org_id"], username=f"plan-{key}",
                     email=email, full_name=f"Plan {key}", role="engineer",
                     hashed_password=get_password_hash("role-secret-1"),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[dept]))
            users[key] = u.id
        change = ChangeRequest(
            change_number="C-P-1", title="plan me", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=users["sales"], customer_relevant=True, status="costing",
            impact_confirmed_at=datetime.utcnow(),
            impact_confirmed_by=users["pm"])
        s.add(change)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id,
                               department_id=depts["Tool Engineer"],
                               rasic_letter="R", verdict="feasible"))
        await s.commit()
        return {"change_id": change.id, "depts": depts, "users": users}


async def _auth(client, key):
    return await login(client, f"plan-{key}@test.io", ENGINEER_PASSWORD)


async def _set(session_factory, cid, **fields):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        for k, v in fields.items():
            setattr(c, k, v)
        await s.commit()


async def _add_positions(session_factory, world):
    """Tool Engineer: 16 support hours and a quoted tool change (20 business
    days, Hasco favourite); APQP: an estimated gauge (10 calendar days)."""
    cid, depts = world["change_id"], world["depts"]
    async with session_factory() as s:
        s.add(CostingPosition(change_id=cid, department_id=depts["Tool Engineer"],
                              label="Support", kind="support_effort", hours=16,
                              created_by=world["users"]["tool"]))
        tool = CostingPosition(change_id=cid, department_id=depts["Tool Engineer"],
                               label="Insert rework", kind="external",
                               pricing="quote", created_by=world["users"]["tool"])
        s.add(tool)
        await s.flush()
        s.add(CostingOffer(position_id=tool.id, vendor_name="Hasco", cost=5000,
                           lead_time_days=20, lead_time_unit="business_days",
                           favorite=True, created_by=world["users"]["tool"]))
        gauge = CostingPosition(change_id=cid, department_id=depts["APQP"],
                                label="Gauge update", kind="external",
                                pricing="estimate", est_cost=800,
                                lead_time_days=10, lead_time_unit="calendar_days",
                                created_by=world["users"]["apqp"])
        s.add(gauge)
        await s.commit()
        return tool.id, gauge.id


async def _plan(client, auth, cid, plan="quote"):
    res = await client.get(f"/api/v1/changes/{cid}/plan?plan={plan}", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _seed(client, auth, cid, plan="quote", replace=False):
    return await client.post(f"/api/v1/changes/{cid}/plan/seed",
                             json={"plan": plan, "replace": replace}, headers=auth)


def _today(n=0):
    return (date.today() + timedelta(days=n)).isoformat()


def _by_name(out):
    return {t["name"]: t for t in out["tasks"]}


# --- seeding --------------------------------------------------------------

async def test_seed_without_costing_positions(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    res = await _seed(client, sales, cid)
    assert res.status_code == 200, res.text
    out = res.json()
    names = [t["name"] for t in out["tasks"]]
    assert names == ["Customer order / go-ahead", "Implementation",
                     "Sampling / trial", "Measurement and validation",
                     "Customer approval (PPAP / ISIR)", "Safety buffer",
                     "Start of production (change)"]
    t = _by_name(out)
    anchor = (date.today() + timedelta(days=7)).isoformat()
    assert t["Customer order / go-ahead"]["start_date"] == anchor
    assert t["Customer order / go-ahead"]["kind"] == "milestone"
    assert t["Implementation"]["duration_days"] == 20
    assert t["Implementation"]["lane"] == "Tool Engineer"
    # Every block hangs off its predecessor: no validation errors.
    assert out["validation"]["errors"] == []
    # The chain is order -> ... -> SOP; the buffer is max(5, 10% of chain).
    chain = 20 + 5 + 7 + 14
    assert t["Safety buffer"]["duration_days"] == max(5, math.ceil(chain * 0.1))
    assert t["Start of production (change)"]["is_critical"] is True
    assert out["summary"]["ideas"] == 0
    assert out["revision"] == 0            # quote plan edits never bump it


async def test_seed_from_costing_positions(client, world, session_factory):
    tool_pos, gauge_pos = await _add_positions(session_factory, world)
    await _set(session_factory, world["change_id"],
               required_by_date=datetime.combine(date.today() + timedelta(days=30),
                                                 datetime.min.time()))
    sales = await _auth(client, "sales")
    out = (await _seed(client, sales, world["change_id"])).json()
    t = _by_name(out)
    order = t["Customer order / go-ahead"]
    assert order["start_date"] == (date.today() + timedelta(days=37)).isoformat()
    eng = t["Tool Engineer engineering"]
    # 16 h = 2 working days = ceil(2*7/5) = 3 calendar days, after the order
    assert eng["duration_days"] == 3
    assert eng["predecessors"] == [order["id"]]
    tool = t["Insert rework - Hasco"]
    assert tool["kind"] == "downtime"            # Tool Engineer -> downtime
    assert tool["duration_days"] == 28           # 20 business days
    assert tool["predecessors"] == [eng["id"]]
    assert tool["source_position_id"] == tool_pos
    gauge = t["Gauge update"]
    assert gauge["kind"] == "supplier" and gauge["duration_days"] == 10
    assert gauge["predecessors"] == [order["id"]]  # APQP has no engineering task
    bank = t["Bank build (idea)"]
    assert bank["is_idea"] is True and bank["duration_days"] == 10
    assert bank["end_date"] == tool["start_date"]
    sampling = t["Sampling / trial"]
    assert set(sampling["predecessors"]) == {tool["id"], gauge["id"]}
    assert sampling["start_date"] == tool["end_date"]
    assert out["summary"]["ideas"] == 1
    assert out["validation"]["errors"] == []


async def test_seed_refuses_without_replace(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    assert (await _seed(client, sales, cid)).status_code == 200
    res = await _seed(client, sales, cid)
    assert res.status_code == 409
    res = await _seed(client, sales, cid, replace=True)
    assert res.status_code == 200
    assert len(res.json()["tasks"]) == 7


# --- the math ---------------------------------------------------------------

def _t(id, start, dur, preds=(), *, kind="work", name=None, lane="L",
       idea=False, dept=None):
    return ChangePlanTask(id=id, name=name if name is not None else f"T{id}",
                          kind=kind, lane=lane, department_id=dept,
                          is_idea=idea, start_date=start, duration_days=dur,
                          predecessors=list(preds), sort_order=id)


D0 = date(2026, 10, 1)


def _d(n):
    return D0 + timedelta(days=n)


async def test_validation_errors_and_warnings():
    tasks = [
        _t(1, _d(0), 5),
        _t(2, _d(3), 4, [1]),                    # starts before 1 ends
        _t(3, _d(10), -1, name=" "),              # negative + empty name
        _t(4, _d(10), 2, [99]),                   # unknown predecessor
        _t(5, _d(0), 12, kind="bank_build"),      # ends after downtime start
        _t(6, _d(8), 3, kind="downtime"),
        _t(7, _d(20), 2, idea=True, lane=None),   # idea, and no owner
    ]
    v = validate_plan(tasks, plan="detailed", release_due=_d(5))
    errors = {e["code"] for e in v["errors"]}
    assert errors == {"dependency_violation", "negative_duration", "empty_name",
                      "unknown_predecessor"}
    warnings = {w["code"] for w in v["warnings"]}
    assert {"after_release_deadline", "no_buffer", "bank_build_late",
            "idea_blocks", "no_owner"} <= warnings
    # a cycle is its own error
    cyc = [_t(1, _d(0), 1, [2]), _t(2, _d(1), 1, [1])]
    assert "cycle" in {e["code"] for e in validate_plan(cyc, plan="quote")["errors"]}
    assert topo_order(cyc) is None
    # a thin buffer: 1 day in a 100-day plan
    thin = [_t(1, _d(0), 99), _t(2, _d(99), 1, [1], kind="buffer")]
    codes = {w["code"] for w in validate_plan(thin, plan="quote")["warnings"]}
    assert "thin_buffer" in codes and "no_buffer" not in codes


async def test_critical_path_slack():
    # A(0-5) -> B(5-10) -> D(10-12); A -> C(5-7) -> D. C has 3 days slack.
    tasks = [_t(1, _d(0), 5), _t(2, _d(5), 5, [1]), _t(3, _d(5), 2, [1]),
             _t(4, _d(10), 2, [2, 3]),
             _t(5, _d(0), 30, idea=True)]          # ideas never count
    slack = critical_path(tasks)
    assert slack == {1: 0, 2: 0, 3: 3, 4: 0}


# --- editing ------------------------------------------------------------------

async def test_schedule_forward_pass_and_bulk_move(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "name": "A", "kind": "work", "lane": "Tool Engineer",
        "start_date": "2026-11-02", "duration_days": 5}, headers=sales)
    assert res.status_code == 200, res.text
    a = _by_name(res.json())["A"]
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "name": "B", "lane": "APQP", "start_date": "2026-11-03",
        "duration_days": 2, "predecessors": [a["id"]]}, headers=sales)
    b = _by_name(res.json())["B"]
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "name": "C", "lane": "APQP", "start_date": "2026-12-01",
        "duration_days": 1, "predecessors": [a["id"]]}, headers=sales)
    out = res.json()
    assert "dependency_violation" in {e["code"] for e in out["validation"]["errors"]}

    res = await client.post(f"/api/v1/changes/{cid}/plan/schedule",
                            json={"plan": "quote"}, headers=sales)
    assert res.status_code == 200, res.text
    t = _by_name(res.json())
    assert t["B"]["start_date"] == "2026-11-07"       # pushed to A's end
    assert t["C"]["start_date"] == "2026-12-01"       # never pulled earlier
    assert res.json()["validation"]["errors"] == []

    # bulk move: A and B two days later, B one day longer
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "updates": [
            {"id": a["id"], "start_date": "2026-11-04"},
            {"id": b["id"], "start_date": "2026-11-09", "duration_days": 3}]},
        headers=sales)
    assert res.status_code == 200, res.text
    t = _by_name(res.json())
    assert (t["A"]["start_date"], t["B"]["start_date"], t["B"]["duration_days"]) \
        == ("2026-11-04", "2026-11-09", 3)
    assert t["B"]["end_date"] == "2026-11-12"

    # milestone durations are normalised to zero
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{b['id']}",
                             json={"kind": "milestone"}, headers=sales)
    assert _by_name(res.json())["B"]["duration_days"] == 0

    # delete removes it from other predecessor lists
    res = await client.delete(f"/api/v1/changes/{cid}/plan/tasks/{a['id']}",
                              headers=sales)
    assert res.status_code == 200, res.text
    t = _by_name(res.json())
    assert "A" not in t and t["B"]["predecessors"] == []


async def test_rights_editors_and_department_progress(client, world, session_factory):
    cid = world["change_id"]
    sales, pack, tool = (await _auth(client, "sales"), await _auth(client, "pack"),
                         await _auth(client, "tool"))
    # an outsider reads the plan but may not shape it
    assert (await _plan(client, pack, cid))["can_edit"] is False
    res = await _seed(client, pack, cid)
    assert res.status_code == 403
    assert (await _seed(client, sales, cid)).status_code == 200
    assert (await _plan(client, sales, cid))["can_edit"] is True

    # the quote plan freezes after acceptance
    await _set(session_factory, cid, status="approved")
    out = await _plan(client, sales, cid)
    assert out["can_edit"] is False
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "name": "late", "start_date": "2026-11-01"}, headers=sales)
    assert res.status_code == 400

    assert (await _seed(client, sales, cid, plan="detailed")).status_code == 200
    await _set(session_factory, cid, status="in_implementation")
    out = await _plan(client, tool, cid, "detailed")
    assert out["progress_department_ids"] == [world["depts"]["Tool Engineer"]]
    t = _by_name(out)
    tool_task, apqp_task = t["Implementation"], t["Measurement and validation"]
    res = await client.patch(
        f"/api/v1/changes/{cid}/plan/tasks/{tool_task['id']}",
        json={"progress_pct": 40, "actual_start": _today(-3)}, headers=tool)
    assert res.status_code == 200, res.text
    assert _by_name(res.json())["Implementation"]["progress_pct"] == 40
    # actual dates report what happened: tomorrow is tolerated (a browser a
    # timezone ahead), later is refused
    for key in ("actual_start", "actual_finish"):
        res = await client.patch(
            f"/api/v1/changes/{cid}/plan/tasks/{tool_task['id']}",
            json={key: _today(2)}, headers=tool)
        assert res.status_code == 400 and "future" in res.json()["detail"]
    res = await client.patch(
        f"/api/v1/changes/{cid}/plan/tasks/{tool_task['id']}",
        json={"actual_finish": _today(1)}, headers=tool)
    assert res.status_code == 200, res.text
    # not its own block
    res = await client.patch(
        f"/api/v1/changes/{cid}/plan/tasks/{apqp_task['id']}",
        json={"progress_pct": 40}, headers=tool)
    assert res.status_code == 403
    # progress yes, dates no
    res = await client.patch(
        f"/api/v1/changes/{cid}/plan/tasks/{tool_task['id']}",
        json={"start_date": "2026-12-01"}, headers=tool)
    assert res.status_code == 403
    # editors may report progress on any block
    res = await client.patch(
        f"/api/v1/changes/{cid}/plan/tasks/{apqp_task['id']}",
        json={"progress_pct": 100}, headers=sales)
    assert res.status_code == 200


# --- feedback and timing validation -------------------------------------------

async def _approved_with_detailed(client, world, session_factory):
    cid = world["change_id"]
    sales = await _auth(client, "sales")
    await _seed(client, sales, cid)
    await _set(session_factory, cid, status="approved")
    res = await _seed(client, sales, cid, plan="detailed")
    assert res.status_code == 200, res.text
    return cid, sales


async def _confirm_all(client, cid, world):
    for key, dept in (("tool", "Tool Engineer"), ("sched", "Scheduling"),
                      ("sales", "Sales")):
        res = await client.post(f"/api/v1/changes/{cid}/plan/feedback", json={
            "department_id": world["depts"][dept], "verdict": "confirmed"},
            headers=await _auth(client, key))
        assert res.status_code == 200, res.text
    return res.json()


async def test_feedback_goes_stale_when_the_plan_moves(client, world, session_factory):
    cid, sales = await _approved_with_detailed(client, world, session_factory)
    fb = (await client.get(f"/api/v1/changes/{cid}/plan/feedback", headers=sales)).json()
    required = {r["department_name"] for r in fb["required"]}
    assert required == {"Tool Engineer", "Scheduling", "Sales"}
    assert fb["all_confirmed"] is False

    # only a member answers for a department
    res = await client.post(f"/api/v1/changes/{cid}/plan/feedback", json={
        "department_id": world["depts"]["Tool Engineer"], "verdict": "confirmed"},
        headers=sales)
    assert res.status_code == 403
    # a concern needs a note
    res = await client.post(f"/api/v1/changes/{cid}/plan/feedback", json={
        "department_id": world["depts"]["Sales"], "verdict": "concern"},
        headers=sales)
    assert res.status_code == 400

    fb = await _confirm_all(client, cid, world)
    assert fb["all_confirmed"] is True
    rev = fb["revision"]

    task = (await _plan(client, sales, cid, "detailed"))["tasks"][1]
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{task['id']}",
                             json={"duration_days": 25}, headers=sales)
    assert res.status_code == 200
    assert res.json()["revision"] == rev + 1
    fb = (await client.get(f"/api/v1/changes/{cid}/plan/feedback", headers=sales)).json()
    assert all(r["stale"] for r in fb["required"])
    assert fb["all_confirmed"] is False


async def test_validate_timing_refusals_and_success(client, world, session_factory):
    cid = world["change_id"]
    sales = await _auth(client, "sales")
    # wrong status
    res = await client.post(f"/api/v1/changes/{cid}/plan/validate-timing", headers=sales)
    assert res.status_code == 400
    await _add_positions(session_factory, world)
    await _seed(client, sales, cid)                     # quote plan with a bank-build idea
    await _set(session_factory, cid, status="approved")
    # no detailed plan
    res = await client.post(f"/api/v1/changes/{cid}/plan/validate-timing", headers=sales)
    assert res.status_code == 400 and "empty" in res.json()["detail"]
    await _seed(client, sales, cid, plan="detailed")
    # the guard names what is missing
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_implementation"}, headers=sales)
    assert res.status_code == 400
    assert "Timing not validated" in res.json()["detail"]
    # only editors validate
    res = await client.post(f"/api/v1/changes/{cid}/plan/validate-timing",
                            headers=await _auth(client, "pack"))
    assert res.status_code == 403
    # the idea block is still in the plan
    await _confirm_all(client, cid, world)
    res = await client.post(f"/api/v1/changes/{cid}/plan/validate-timing", headers=sales)
    assert res.status_code == 400 and "Idea" in res.json()["detail"]
    idea = next(t for t in (await _plan(client, sales, cid, "detailed"))["tasks"]
                if t["is_idea"])
    await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{idea['id']}",
                       json={"is_idea": False}, headers=sales)
    # that edit made the confirmations stale
    res = await client.post(f"/api/v1/changes/{cid}/plan/validate-timing", headers=sales)
    assert res.status_code == 400 and "confirmed" in res.json()["detail"]
    await _confirm_all(client, cid, world)
    res = await client.post(f"/api/v1/changes/{cid}/plan/validate-timing", headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["baseline_set"] is True
    assert all(t["baseline_start"] == t["start_date"]
               and t["baseline_finish"] == t["end_date"] for t in out["tasks"])
    assert out["can_edit"] is False and out["can_edit_dates"] is True
    fb = (await client.get(f"/api/v1/changes/{cid}/plan/feedback", headers=sales)).json()
    assert fb["validated_at"] is not None and fb["validated_by_name"] == "Plan sales"
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_implementation"}, headers=sales)
    assert res.status_code == 200, res.text
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=sales)).json()
    assert "timing_validated" in [e["action"] for e in log]


async def _baselined(client, world, session_factory):
    cid, sales = await _approved_with_detailed(client, world, session_factory)
    await _confirm_all(client, cid, world)
    res = await client.post(f"/api/v1/changes/{cid}/plan/validate-timing", headers=sales)
    assert res.status_code == 200, res.text
    await _set(session_factory, cid, status="in_implementation")
    return cid, sales


async def test_deviations_after_baseline(client, world, session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    t = _by_name(await _plan(client, sales, cid, "detailed"))
    impl = t["Implementation"]
    url = f"/api/v1/changes/{cid}/plan/tasks/{impl['id']}"
    # no reason, no move
    res = await client.patch(url, json={"duration_days": 25}, headers=sales)
    assert res.status_code == 400 and "reason" in res.json()["detail"]
    # structure is frozen
    res = await client.patch(url, json={"lane": "APQP"}, headers=sales)
    assert res.status_code == 400
    res = await client.delete(url, headers=sales)
    assert res.status_code == 400
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "detailed", "name": "new", "start_date": "2026-11-01"}, headers=sales)
    assert res.status_code == 400

    res = await client.patch(url, json={"duration_days": 25,
                                        "reason": "supplier late"}, headers=sales)
    assert res.status_code == 200, res.text
    devs = (await client.get(f"/api/v1/changes/{cid}/plan/deviations",
                             headers=sales)).json()
    by_task = {x["task_name"]: x for x in devs}
    d = by_task["Implementation"]
    assert d["status"] == "open" and d["caused_by_task_id"] is None
    assert d["slip_days"] == 5 and d["reason"] == "supplier late"
    assert d["created_by_name"] == "Plan sales"
    # The move pushes every successor along its link: one deviation each,
    # same reason, naming the block that caused it, and the finish impact is
    # the real new finish of the plan.
    pushed = [x for x in devs if x["caused_by_task_id"] == impl["id"]]
    assert {x["task_name"] for x in pushed} == {
        "Sampling / trial", "Measurement and validation",
        "Customer approval (PPAP / ISIR)", "Safety buffer",
        "Start of production (change)"}
    assert len(devs) == 1 + len(pushed)
    for x in pushed:
        assert x["caused_by_task_name"] == "Implementation"
        assert x["reason"] == "supplier late" and x["slip_days"] == 5
    assert {x["finish_impact_days"] for x in devs} == {5}
    out = await _plan(client, sales, cid, "detailed")
    assert "dependency_violation" not in {
        e["code"] for e in out["validation"]["errors"]}
    # Moving the last milestone moves the finish again.
    sop = _by_name(out)["Start of production (change)"]
    new_start = (date.fromisoformat(sop["start_date"]) + timedelta(days=5)).isoformat()
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{sop['id']}",
                             json={"start_date": new_start, "reason": "late PPAP"},
                             headers=sales)
    assert res.status_code == 200, res.text
    devs = (await client.get(f"/api/v1/changes/{cid}/plan/deviations",
                             headers=sales)).json()
    assert len(devs) == 7
    assert devs[0]["finish_impact_days"] == 5 and devs[0]["slip_days"] == 10

    # a bulk move after the baseline: one deviation per task, same reason
    val = t["Measurement and validation"]
    appr = t["Customer approval (PPAP / ISIR)"]
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "detailed", "reason": "shift",
        "updates": [{"id": val["id"], "start_date": "2027-06-01"},
                    {"id": appr["id"], "start_date": "2027-06-10"}]},
        headers=sales)
    assert res.status_code == 200, res.text
    devs = (await client.get(f"/api/v1/changes/{cid}/plan/deviations",
                             headers=sales)).json()
    # two moved, buffer and start of production pushed behind them
    shift = [x for x in devs if x["reason"] == "shift"]
    assert len(devs) == 11 and len(shift) == 4
    assert {x["task_name"]: x["caused_by_task_name"] for x in shift} == {
        "Measurement and validation": None,
        "Customer approval (PPAP / ISIR)": None,
        "Safety buffer": "Customer approval (PPAP / ISIR)",
        "Start of production (change)": "Customer approval (PPAP / ISIR)"}

    # decide: an outsider may not
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{d['id']}/lock",
                            json={}, headers=await _auth(client, "pack"))
    assert res.status_code == 403
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{d['id']}/lock",
                            json={"note": "absorbed"}, headers=await _auth(client, "pm"))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "locked"
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{d['id']}/lock",
                            json={}, headers=sales)
    assert res.status_code == 400

    other = devs[0]["id"]
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{other}/escalate",
                            json={"note": ""}, headers=sales)
    assert res.status_code == 400
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{other}/escalate",
                            json={"note": "customer informed of +2 weeks"},
                            headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "escalated"
    esc = (await client.get(f"/api/v1/changes/{cid}/implementation/escalations",
                            headers=sales)).json()
    assert [e["direction"] for e in esc] == ["customer"]
    assert res.json()["escalation_id"] == esc[0]["id"]
    log = [e["action"] for e in (await client.get(
        f"/api/v1/changes/{cid}/changelog", headers=sales)).json()]
    assert {"plan_deviation", "deviation_locked", "deviation_escalated"} <= set(log)


async def test_my_actions_for_the_plan(client, world, session_factory):
    cid, sales = await _approved_with_detailed(client, world, session_factory)
    tool = await _auth(client, "tool")
    kinds = {a["kind"]: a for a in (await client.get(
        f"/api/v1/changes/{cid}/my-actions", headers=tool)).json()["actions"]}
    assert kinds["plan_feedback"]["target_tab"] == "timing"
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=tool)).json()
    assert "plan_feedback" in [t["kind"] for t in tasks]
    await _confirm_all(client, cid, world)
    kinds = {a["kind"] for a in (await client.get(
        f"/api/v1/changes/{cid}/my-actions", headers=sales)).json()["actions"]}
    assert "timing_validate" in kinds and "plan_feedback" not in kinds


# --- exports ----------------------------------------------------------------------

async def test_mspdi_xml_and_csv(client, world, session_factory):
    await _add_positions(session_factory, world)
    cid, sales = world["change_id"], await _auth(client, "sales")
    await _seed(client, sales, cid)
    plan = await _plan(client, sales, cid)
    res = await client.get(f"/api/v1/changes/{cid}/plan/export.xml?plan=quote",
                           headers=sales)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/xml")
    assert 'C-P-1-quote.xml' in res.headers["content-disposition"]
    root = ET.fromstring(res.content)
    assert root.tag == f"{NS}Project"
    tasks = root.find(f"{NS}Tasks").findall(f"{NS}Task")
    real = [t for t in plan["tasks"] if not t["is_idea"]]
    assert len(tasks) == len(real)
    links = root.findall(f".//{NS}PredecessorLink")
    assert links and links[0].find(f"{NS}Type").text == "1"
    first = tasks[1]
    assert first.find(f"{NS}DurationFormat").text == "8"
    d = int(first.find(f"{NS}Duration").text[2:].split("H")[0]) // 24
    assert d == real[1]["duration_days"]
    assert root.find(f"{NS}Resources") is not None

    res = await client.get(f"/api/v1/changes/{cid}/plan/export.csv?plan=quote",
                           headers=sales)
    assert res.status_code == 200
    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0][:3] == ["ID", "Name", "Lane"]
    assert len(rows) == 1 + len(plan["tasks"])


async def test_mspdi_carries_the_baseline(client, world, session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    res = await client.get(f"/api/v1/changes/{cid}/plan/export.xml?plan=detailed",
                           headers=sales)
    root = ET.fromstring(res.content)
    baselines = root.findall(f".//{NS}Baseline")
    assert baselines and baselines[0].find(f"{NS}Number").text == "0"


# --- Gantt 2.0: links, summaries, constraints, calendar, batch, import --------

async def _task(client, auth, cid, name, start, dur, plan="quote", **extra):
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": plan, "name": name, "lane": "APQP", "start_date": start,
        "duration_days": dur, **extra}, headers=auth)
    assert res.status_code == 200, res.text
    return _by_name(res.json())[name]


async def test_predecessors_are_served_from_links(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    a = await _task(client, sales, cid, "A", "2026-11-02", 5)
    b = await _task(client, sales, cid, "B", "2026-11-07", 2, predecessors=[a["id"]])
    out = await _plan(client, sales, cid)
    assert [(lk["from_task_id"], lk["to_task_id"], lk["type"], lk["lag_days"])
            for lk in out["links"]] == [(a["id"], b["id"], "FS", 0)]
    t = _by_name(out)
    assert t["B"]["predecessors"] == [a["id"]]
    assert out["calendar"] == {"mode": "calendar", "workdays": [1, 2, 3, 4, 5],
                               "holidays": []}
    for key in ("parent_id", "constraint_type", "constraint_date", "total_slack",
                "free_slack", "wbs", "is_summary"):
        assert key in t["A"]
    assert t["A"]["wbs"] == "1" and t["B"]["wbs"] == "2"
    # the legacy list replaces the FS links, other link types stay
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{b['id']}",
                             json={"predecessors": []}, headers=sales)
    assert res.json()["links"] == []


async def test_link_crud_rights_and_baseline_lock(client, world, session_factory):
    cid = world["change_id"]
    sales, pack = await _auth(client, "sales"), await _auth(client, "pack")
    a = await _task(client, sales, cid, "A", "2026-11-02", 5)
    b = await _task(client, sales, cid, "B", "2026-11-02", 2)
    url = f"/api/v1/changes/{cid}/plan/links"
    body = {"plan": "quote", "from_task_id": a["id"], "to_task_id": b["id"],
            "type": "SS", "lag_days": 2}
    assert (await client.post(url, json=body, headers=pack)).status_code == 403
    res = await client.post(url, json=body, headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    lk = out["links"][0]
    assert (lk["type"], lk["lag_days"]) == ("SS", 2)
    # SS+2 on dates as they stand: B starts before A starts + 2
    assert "dependency_violation" in {e["code"] for e in out["validation"]["errors"]}
    # no duplicates, no self links, no unknown type
    for bad in ({**body, "type": "FS"}, {**body, "to_task_id": a["id"]},
                {**body, "type": "XX", "to_task_id": b["id"]}):
        assert (await client.post(url, json=bad, headers=sales)).status_code == 400
    res = await client.patch(f"{url}/{lk['id']}", json={"type": "FF", "lag_days": -1},
                             headers=sales)
    assert res.status_code == 200
    assert (res.json()["links"][0]["type"], res.json()["links"][0]["lag_days"]) \
        == ("FF", -1)
    res = await client.post(f"/api/v1/changes/{cid}/plan/schedule",
                            json={"plan": "quote"}, headers=sales)
    t = _by_name(res.json())
    # FF-1: B ends no earlier than A's end - 1 = 11-06, so B starts 11-04
    assert t["B"]["start_date"] == "2026-11-04" and t["B"]["end_date"] == "2026-11-06"
    assert (await client.delete(f"{url}/{lk['id']}", headers=pack)).status_code == 403
    assert (await client.delete(f"{url}/9999", headers=sales)).status_code == 404
    res = await client.delete(f"{url}/{lk['id']}", headers=sales)
    assert res.status_code == 200 and res.json()["links"] == []



async def test_links_frozen_after_baseline(client, world, session_factory):
    url = f"/api/v1/changes/{world['change_id']}/plan/links"
    cid2, sales = await _baselined(client, world, session_factory)
    out = await _plan(client, sales, cid2, "detailed")
    t = _by_name(out)
    first, other = t["Implementation"], t["Safety buffer"]
    res = await client.post(url, json={
        "plan": "detailed", "from_task_id": first["id"], "to_task_id": other["id"],
        "type": "SS"}, headers=sales)
    assert res.status_code == 400
    lid = out["links"][0]["id"]
    assert (await client.patch(f"{url}/{lid}", json={"lag_days": 3},
                               headers=sales)).status_code == 400
    assert (await client.delete(f"{url}/{lid}", headers=sales)).status_code == 400
    res = await client.patch(f"/api/v1/changes/{cid2}/plan/tasks/{first['id']}",
                             json={"constraint_type": "snet",
                                   "constraint_date": "2026-12-01"}, headers=sales)
    assert res.status_code == 400
    res = await client.put(f"/api/v1/changes/{cid2}/plan/calendar",
                           json={"mode": "working"}, headers=sales)
    assert res.status_code == 400


async def test_summaries_constraints_and_negative_slack(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    s = await _task(client, sales, cid, "Phase", "2026-01-01", 1)
    a = await _task(client, sales, cid, "A", "2026-11-02", 5, parent_id=s["id"])
    b = await _task(client, sales, cid, "B", "2026-11-09", 3, parent_id=s["id"],
                    constraint_type="fnlt", constraint_date="2026-11-10")
    out = await _plan(client, sales, cid)
    t = _by_name(out)
    assert t["Phase"]["is_summary"] is True
    assert (t["Phase"]["start_date"], t["Phase"]["end_date"]) == \
        ("2026-11-02", "2026-11-12")
    assert [t[n]["wbs"] for n in ("Phase", "A", "B")] == ["1", "1.1", "1.2"]
    # B misses its finish-no-later-than by 2 days: negative slack is critical
    assert t["B"]["total_slack"] == -2 and t["B"]["is_critical"] is True
    assert b["id"] in out["summary"]["critical_ids"]
    assert "constraint_conflict" in {w["code"] for w in out["validation"]["warnings"]}
    # a summary's dates follow its blocks
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{s['id']}",
                             json={"start_date": "2026-12-01"}, headers=sales)
    assert res.status_code == 400
    # a block cannot move under its own child
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{s['id']}",
                             json={"parent_id": a["id"]}, headers=sales)
    assert res.status_code == 400
    # a constraint needs a date; asap clears it
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{a['id']}",
                             json={"constraint_type": "mso"}, headers=sales)
    assert res.status_code == 400
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{b['id']}",
                             json={"constraint_type": "asap"}, headers=sales)
    assert _by_name(res.json())["B"]["constraint_date"] is None
    # deleting the summary hangs its blocks on its parent (top level)
    res = await client.delete(f"/api/v1/changes/{cid}/plan/tasks/{s['id']}",
                              headers=sales)
    t = _by_name(res.json())
    assert t["A"]["parent_id"] is None and t["B"]["is_summary"] is False


async def test_working_calendar(client, world):
    sales, pack = await _auth(client, "sales"), await _auth(client, "pack")
    cid = world["change_id"]
    url = f"/api/v1/changes/{cid}/plan/calendar"
    body = {"mode": "working", "workdays": [1, 2, 3, 4, 5],
            "holidays": ["2026-11-11"]}
    assert (await client.put(url, json=body, headers=pack)).status_code == 403
    assert (await client.put(url, json={"mode": "lunar"},
                             headers=sales)).status_code == 400
    a = await _task(client, sales, cid, "A", "2026-11-07", 5)   # a Saturday
    res = await client.put(url, json=body, headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["calendar"] == body
    t = _by_name(out)
    # snapped to Monday 9 Nov; Mon, Tue, (Wed holiday), Thu, Fri, Mon -> Tue 17
    assert t["A"]["start_date"] == "2026-11-09" and t["A"]["end_date"] == "2026-11-17"
    b = await _task(client, sales, cid, "B", "2026-11-09", 1, predecessors=[a["id"]])
    res = await client.post(f"/api/v1/changes/{cid}/plan/schedule",
                            json={"plan": "quote"}, headers=sales)
    assert _by_name(res.json())["B"]["start_date"] == "2026-11-17"
    assert b["duration_days"] == 1


async def test_batch_changeset_with_temp_ids(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    a = await _task(client, sales, cid, "A", "2026-11-02", 5)
    url = f"/api/v1/changes/{cid}/plan/changes"
    res = await client.post(url, json={"plan": "quote", "changes": {
        "tasks_upsert": [
            {"id": "tmp-1", "name": "Phase", "start_date": "2026-11-02",
             "duration_days": 0},
            {"id": "tmp-2", "name": "Child", "start_date": "2026-11-02",
             "duration_days": 3, "parent_id": "tmp-1", "lane": "APQP"},
            {"id": a["id"], "duration_days": 4, "parent_id": "tmp-1"},
        ],
        "links_upsert": [{"id": "tmp-l1", "from_task_id": a["id"],
                          "to_task_id": "tmp-2", "type": "SS", "lag_days": 1}],
    }}, headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    ids = out["id_map"]
    assert set(ids) == {"tmp-1", "tmp-2"}
    assert set(out["link_id_map"]) == {"tmp-l1"}
    t = _by_name(out)
    assert t["Child"]["id"] == ids["tmp-2"] and t["Child"]["parent_id"] == ids["tmp-1"]
    assert t["A"]["parent_id"] == ids["tmp-1"] and t["A"]["duration_days"] == 4
    assert t["Phase"]["is_summary"] is True
    assert (out["links"][0]["from_task_id"], out["links"][0]["to_task_id"]) \
        == (a["id"], ids["tmp-2"])
    log = [e["action"] for e in (await client.get(
        f"/api/v1/changes/{cid}/changelog", headers=sales)).json()]
    assert "plan_changes" in log

    # atomic: an unknown reference in the set leaves the plan untouched
    before = await _plan(client, sales, cid)
    res = await client.post(url, json={"plan": "quote", "changes": {
        "tasks_upsert": [{"id": "tmp-9", "name": "Ghost", "start_date": "2026-11-02"}],
        "tasks_delete": [a["id"]],
        "links_upsert": [{"from_task_id": "tmp-9", "to_task_id": "tmp-nope"}],
    }}, headers=sales)
    assert res.status_code == 400
    after = await _plan(client, sales, cid)
    assert [x["id"] for x in after["tasks"]] == [x["id"] for x in before["tasks"]]
    assert after["links"] == before["links"]
    # delete + link delete in one set; an outsider may not
    res = await client.post(url, json={"plan": "quote", "changes": {
        "tasks_delete": [a["id"]]}}, headers=await _auth(client, "pack"))
    assert res.status_code == 403
    res = await client.post(url, json={"plan": "quote", "changes": {
        "tasks_delete": [a["id"]],
        "links_delete": [out["links"][0]["id"]]}}, headers=sales)
    assert res.status_code == 200, res.text
    assert "A" not in _by_name(res.json()) and res.json()["links"] == []


async def test_batch_after_baseline_moves_dates_as_deviations(client, world,
                                                              session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    t = _by_name(await _plan(client, sales, cid, "detailed"))
    impl = t["Implementation"]
    url = f"/api/v1/changes/{cid}/plan/changes"
    move = {"plan": "detailed", "changes": {"tasks_upsert": [
        {"id": impl["id"], "duration_days": impl["duration_days"] + 3}]}}
    res = await client.post(url, json=move, headers=sales)
    assert res.status_code == 400 and "reason" in res.json()["detail"]
    res = await client.post(url, json={**move, "reason": "late steel"}, headers=sales)
    assert res.status_code == 200, res.text
    devs = (await client.get(f"/api/v1/changes/{cid}/plan/deviations",
                             headers=sales)).json()
    # the move and the five successors it pushed, one reason
    assert len(devs) == 6 and {x["reason"] for x in devs} == {"late steel"}
    assert sum(1 for x in devs if x["caused_by_task_id"] == impl["id"]) == 5
    # structure stays frozen
    res = await client.post(url, json={"plan": "detailed", "changes": {
        "tasks_upsert": [{"id": "tmp-1", "name": "new", "start_date": "2026-12-01"}]}},
        headers=sales)
    assert res.status_code == 400


async def test_mspdi_import_round_trips_export(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    res = await client.put(f"/api/v1/changes/{cid}/plan/calendar", json={
        "mode": "working", "workdays": [1, 2, 3, 4, 5],
        "holidays": ["2026-11-11"]}, headers=sales)
    assert res.status_code == 200
    s = await _task(client, sales, cid, "Phase", "2026-11-02", 1)
    a = await _task(client, sales, cid, "Design", "2026-11-02", 3, parent_id=s["id"],
                    constraint_type="snet", constraint_date="2026-10-30")
    b = await _task(client, sales, cid, "Build", "2026-11-05", 4, parent_id=s["id"],
                    constraint_type="fnlt", constraint_date="2026-11-20")
    m = await _task(client, sales, cid, "Go", "2026-11-12", 0, kind="milestone",
                    constraint_type="mso", constraint_date="2026-11-13")
    for f, to, typ, lag in ((a, b, "SS", 2), (b, m, "FF", -1)):
        res = await client.post(f"/api/v1/changes/{cid}/plan/links", json={
            "plan": "quote", "from_task_id": f["id"], "to_task_id": to["id"],
            "type": typ, "lag_days": lag}, headers=sales)
        assert res.status_code == 200, res.text
    before = await _plan(client, sales, cid)
    xml = (await client.get(f"/api/v1/changes/{cid}/plan/export.xml?plan=quote",
                            headers=sales)).content
    root = ET.fromstring(xml)
    by_name = {x.find(f"{NS}Name").text: x for x in root.iter(f"{NS}Task")}
    assert by_name["Phase"].find(f"{NS}Summary").text == "1"
    assert by_name["Design"].find(f"{NS}OutlineLevel").text == "2"
    assert by_name["Design"].find(f"{NS}OutlineNumber").text == "1.1"
    link = by_name["Build"].find(f"{NS}PredecessorLink")
    assert (link.find(f"{NS}Type").text, link.find(f"{NS}LinkLag").text) == ("3", "9600")
    assert by_name["Build"].find(f"{NS}ConstraintType").text == "7"
    assert by_name["Go"].find(f"{NS}ConstraintType").text == "2"

    # outsider may not import; a bad file is a 400
    files = {"file": ("plan.xml", xml, "application/xml")}
    res = await client.post(f"/api/v1/changes/{cid}/plan/import",
                            data={"plan": "quote", "replace": "true"}, files=files,
                            headers=await _auth(client, "pack"))
    assert res.status_code == 403
    res = await client.post(f"/api/v1/changes/{cid}/plan/import",
                            data={"plan": "quote", "replace": "true"},
                            files={"file": ("x.xml", b"<nope", "application/xml")},
                            headers=sales)
    assert res.status_code == 400
    res = await client.post(f"/api/v1/changes/{cid}/plan/import",
                            data={"plan": "quote", "replace": "true"}, files=files,
                            headers=sales)
    assert res.status_code == 200, res.text
    after = res.json()
    assert after["calendar"] == before["calendar"]

    def shape(p):
        names = {t["id"]: t["name"] for t in p["tasks"]}
        tasks = sorted((t["name"], t["start_date"], t["duration_days"], t["end_date"],
                        names.get(t["parent_id"]), t["constraint_type"],
                        t["constraint_date"], t["kind"], t["lane"], t["wbs"])
                       for t in p["tasks"])
        links = sorted((names[lk["from_task_id"]], names[lk["to_task_id"]],
                        lk["type"], lk["lag_days"]) for lk in p["links"])
        return tasks, links
    assert shape(after) == shape(before)

    # append mode adds the blocks again next to the existing ones
    res = await client.post(f"/api/v1/changes/{cid}/plan/import",
                            data={"plan": "quote"}, files=files, headers=sales)
    assert len(res.json()["tasks"]) == 2 * len(before["tasks"])


# --- review fixes -----------------------------------------------------------

async def test_csv_quotes_formula_cells(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    await _task(client, sales, cid, "=HYPERLINK(\"http://x\")", "2026-11-02", 1)
    await _task(client, sales, cid, "@SUM(1)", "2026-11-02", 1)
    res = await client.get(f"/api/v1/changes/{cid}/plan/export.csv?plan=quote",
                           headers=sales)
    rows = list(csv.reader(io.StringIO(res.text)))
    names = [r[1] for r in rows[1:]]
    assert names == ["'=HYPERLINK(\"http://x\")", "'@SUM(1)"]


async def test_long_names_and_unknown_departments(client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "name": "x" * 201, "start_date": "2026-11-02"}, headers=sales)
    assert res.status_code == 422
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "name": "ok", "start_date": "2026-11-02",
        "department_id": 99999}, headers=sales)
    assert res.status_code == 400 and "does not exist" in res.json()["detail"]
    # a long costing label is cut to fit the column instead of failing the seed
    async with session_factory() as s:
        s.add(CostingPosition(change_id=cid, department_id=world["depts"]["APQP"],
                              label="L" * 250, kind="external", pricing="estimate",
                              est_cost=10, lead_time_days=5,
                              lead_time_unit="calendar_days",
                              created_by=world["users"]["apqp"]))
        await s.commit()
    res = await _seed(client, sales, cid, replace=True)
    assert res.status_code == 200, res.text
    assert max(len(t["name"]) for t in res.json()["tasks"]) == 200


async def test_feedback_for_unknown_department(client, world, session_factory):
    cid, sales = await _approved_with_detailed(client, world, session_factory)
    res = await client.post(f"/api/v1/changes/{cid}/plan/feedback", json={
        "department_id": 99999, "verdict": "confirmed"}, headers=sales)
    assert res.status_code == 400


async def test_seeded_supplier_uses_the_chosen_offers_lead_time(client, world,
                                                               session_factory):
    cid, depts = world["change_id"], world["depts"]
    async with session_factory() as s:
        pos = CostingPosition(change_id=cid, department_id=depts["APQP"],
                              label="Gauge", kind="external", pricing="quote",
                              created_by=world["users"]["apqp"])
        s.add(pos)
        await s.flush()
        s.add(CostingOffer(position_id=pos.id, vendor_name="Slow", cost=100,
                           lead_time_days=30, lead_time_unit="calendar_days",
                           favorite=True, created_by=world["users"]["apqp"]))
        s.add(CostingOffer(position_id=pos.id, vendor_name="Fast", cost=150,
                           lead_time_days=6, lead_time_unit="calendar_days",
                           chosen=True, created_by=world["users"]["apqp"]))
        await s.commit()
    out = (await _seed(client, await _auth(client, "sales"), cid)).json()
    t = _by_name(out)
    assert t["Gauge - Fast"]["duration_days"] == 6


async def test_deviation_decisions_only_while_the_plan_runs(client, world,
                                                            session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    impl = _by_name(await _plan(client, sales, cid, "detailed"))["Implementation"]
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{impl['id']}",
                             json={"duration_days": 30, "reason": "late"},
                             headers=sales)
    assert res.status_code == 200
    did = (await client.get(f"/api/v1/changes/{cid}/plan/deviations",
                            headers=sales)).json()[0]["id"]
    await _set(session_factory, cid, status="released")
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{did}/lock",
                            json={}, headers=sales)
    assert res.status_code == 400
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{did}/escalate",
                            json={"note": "x"}, headers=sales)
    assert res.status_code == 400
    await _set(session_factory, cid, status="in_validation")
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{did}/lock",
                            json={}, headers=sales)
    assert res.status_code == 200


# --- review round 2 ------------------------------------------------------------

async def test_legacy_predecessors_convert_on_read(client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    a = await _task(client, sales, cid, "A", "2026-11-02", 5)
    b = await _task(client, sales, cid, "B", "2026-11-09", 2)
    # a row written by pre-088 code: only the legacy list
    async with session_factory() as s:
        row = await s.get(ChangePlanTask, b["id"])
        row.predecessors = [a["id"], a["id"], 99999, b["id"]]
        await s.commit()
    out = await _plan(client, sales, cid)
    assert [(lk["from_task_id"], lk["to_task_id"], lk["type"]) for lk in out["links"]] \
        == [(a["id"], b["id"], "FS")]
    assert _by_name(out)["B"]["predecessors"] == [a["id"]]
    async with session_factory() as s:
        assert (await s.get(ChangePlanTask, b["id"])).predecessors == []
    # read again: nothing more to convert, no duplicate
    assert len((await _plan(client, sales, cid))["links"]) == 1


async def test_each_plan_has_its_own_calendar(client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    url = f"/api/v1/changes/{cid}/plan/calendar"
    await _task(client, sales, cid, "A", "2026-11-02", 5)
    working = {"mode": "working", "workdays": [1, 2, 3, 4, 5], "holidays": []}
    res = await client.put(f"{url}?plan=quote", json=working, headers=sales)
    assert res.status_code == 200 and res.json()["calendar"] == working
    # the detailed plan is seeded with the quote plan's calendar
    await _set(session_factory, cid, status="approved")
    res = await _seed(client, sales, cid, plan="detailed")
    assert res.status_code == 200, res.text
    assert (await _plan(client, sales, cid, "detailed"))["calendar"] == working
    # the quote plan is frozen once accepted: its calendar is too, and a
    # change of the detailed calendar leaves it alone
    res = await client.put(f"{url}?plan=quote", json={"mode": "calendar"},
                           headers=sales)
    assert res.status_code == 400
    res = await client.put(f"{url}?plan=detailed", json={
        "mode": "calendar", "workdays": [1, 2, 3, 4, 5], "holidays": []},
        headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["calendar"]["mode"] == "calendar"
    quote = await _plan(client, sales, cid, "quote")
    assert quote["calendar"] == working
    assert _by_name(quote)["A"]["end_date"] == "2026-11-07"   # 5 working days
    # the older flat shape still reads as the calendar of both plans
    await _set(session_factory, cid, plan_calendar=working)
    assert (await _plan(client, sales, cid, "detailed"))["calendar"] == working


async def test_summary_rules_on_write(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    s = await _task(client, sales, cid, "Phase", "2026-11-02", 1)
    await _task(client, sales, cid, "A", "2026-11-02", 3, parent_id=s["id"])
    x = await _task(client, sales, cid, "X", "2026-10-26", 2)
    url = f"/api/v1/changes/{cid}/plan/links"
    for typ in ("FF", "SF"):
        res = await client.post(url, json={"plan": "quote", "from_task_id": x["id"],
                                           "to_task_id": s["id"], "type": typ},
                                headers=sales)
        assert res.status_code == 400 and "summary" in res.json()["detail"]
    # FS and SS into a summary, anything out of it: fine
    res = await client.post(url, json={"plan": "quote", "from_task_id": x["id"],
                                       "to_task_id": s["id"], "type": "SS"},
                            headers=sales)
    assert res.status_code == 200, res.text
    lid = res.json()["links"][0]["id"]
    # ... and it cannot be turned into FF afterwards
    res = await client.patch(f"{url}/{lid}", json={"type": "FF"}, headers=sales)
    assert res.status_code == 400
    # mso / mfo on a summary
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{s['id']}", json={
        "constraint_type": "mso", "constraint_date": "2026-11-02"}, headers=sales)
    assert res.status_code == 400 and "summary" in res.json()["detail"]
    # snet on a summary is fine
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{s['id']}", json={
        "constraint_type": "snet", "constraint_date": "2026-11-02"}, headers=sales)
    assert res.status_code == 200, res.text
    # a block with mfo cannot become a summary, nor one with an FF link in
    m = await _task(client, sales, cid, "M", "2026-11-02", 2,
                    constraint_type="mfo", constraint_date="2026-11-04")
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "name": "under M", "start_date": "2026-11-02",
        "parent_id": m["id"]}, headers=sales)
    assert res.status_code == 400 and "summary" in res.json()["detail"]
    res = await client.post(f"/api/v1/changes/{cid}/plan/changes", json={
        "plan": "quote", "changes": {"tasks_upsert": [
            {"id": x["id"], "parent_id": m["id"]}]}}, headers=sales)
    assert res.status_code == 400
    y = await _task(client, sales, cid, "Y", "2026-11-02", 2)
    await client.post(url, json={"plan": "quote", "from_task_id": x["id"],
                                 "to_task_id": y["id"], "type": "FF"}, headers=sales)
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{x['id']}",
                             json={"parent_id": y["id"]}, headers=sales)
    assert res.status_code == 400


async def test_batch_review_fixes(client, world):
    sales, pack = await _auth(client, "sales"), await _auth(client, "pack")
    cid = world["change_id"]
    a = await _task(client, sales, cid, "A", "2026-11-02", 5)
    b = await _task(client, sales, cid, "B", "2026-11-09", 2, predecessors=[a["id"]])
    s = await _task(client, sales, cid, "Phase", "2026-11-02", 1)
    await _task(client, sales, cid, "Kid", "2026-11-02", 3, parent_id=s["id"])
    url = f"/api/v1/changes/{cid}/plan/changes"

    async def post(changes, headers=sales):
        return await client.post(url, json={"plan": "quote", "changes": changes},
                                 headers=headers)
    # duplicate temp ids
    res = await post({"tasks_upsert": [
        {"id": "tmp-1", "name": "x", "start_date": "2026-11-02"},
        {"id": "tmp-1", "name": "y", "start_date": "2026-11-02"}]})
    assert res.status_code == 400 and "twice" in res.json()["detail"]
    res = await post({"links_upsert": [
        {"id": "l-1", "from_task_id": a["id"], "to_task_id": s["id"]},
        {"id": "l-1", "from_task_id": b["id"], "to_task_id": s["id"]}]})
    assert res.status_code == 400
    # predecessors go through the link checks: self, reverse
    res = await post({"tasks_upsert": [
        {"id": "tmp-2", "name": "self", "start_date": "2026-11-02",
         "predecessors": ["tmp-2"]}]})
    assert res.status_code == 400
    res = await post({"tasks_upsert": [{"id": a["id"], "predecessors": [b["id"]]}]})
    assert res.status_code == 400 and "already linked" in res.json()["detail"]
    # a summary's dates: a change is refused, the same value is not
    res = await post({"tasks_upsert": [{"id": s["id"], "start_date": "2026-12-01"}]})
    assert res.status_code == 400 and "summary" in res.json()["detail"]
    res = await post({"tasks_upsert": [{"id": s["id"], "start_date": "2026-11-02",
                                        "name": "Phase 1"}]})
    assert res.status_code == 200, res.text
    # an entry without fields is a no-op, not a rights question
    before = await _plan(client, sales, cid)
    res = await post({"tasks_upsert": [{"id": a["id"]}]}, headers=pack)
    assert res.status_code == 200, res.text
    assert res.json()["revision"] == before["revision"]
    # sort_order null
    res = await post({"tasks_upsert": [{"id": a["id"], "sort_order": None}]})
    assert res.status_code == 400
    # the outline stops at 50 levels
    chain = [{"id": "d-0", "name": "d0", "start_date": "2026-11-02",
              "duration_days": 1}]
    for i in range(1, 51):
        chain.append({"id": f"d-{i}", "name": f"d{i}", "start_date": "2026-11-02",
                      "duration_days": 1, "parent_id": f"d-{i - 1}"})
    res = await post({"tasks_upsert": chain})
    assert res.status_code == 400 and "50" in res.json()["detail"]
    res = await post({"tasks_upsert": chain[:50]})
    assert res.status_code == 200, res.text


async def test_api_bounds(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    a = await _task(client, sales, cid, "A", "2026-11-02", 5)
    b = await _task(client, sales, cid, "B", "2026-11-09", 2)
    url = f"/api/v1/changes/{cid}/plan"
    bad = [
        ("post", f"{url}/tasks", {"plan": "quote", "name": "x",
                                  "start_date": "9999-01-01"}),
        ("post", f"{url}/tasks", {"plan": "quote", "name": "x",
                                  "start_date": "2026-11-02",
                                  "duration_days": 10 ** 9}),
        ("patch", f"{url}/tasks/{a['id']}", {"duration_days": 99999999}),
        ("post", f"{url}/links", {"plan": "quote", "from_task_id": a["id"],
                                  "to_task_id": b["id"], "lag_days": 10 ** 6}),
        ("post", f"{url}/changes", {"plan": "quote", "changes": {"tasks_upsert": [
            {"id": a["id"], "start_date": "0001-01-01"}]}}),
        ("put", f"{url}/calendar", {"mode": "working", "holidays": ["1066-10-14"]}),
    ]
    for method, u, body in bad:
        res = await getattr(client, method)(u, json=body, headers=sales)
        assert res.status_code == 422, (u, body, res.text)


async def test_csv_does_not_double_the_idea_suffix(client, world, session_factory):
    await _add_positions(session_factory, world)
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    await _seed(client, sales, cid)
    res = await client.get(f"/api/v1/changes/{cid}/plan/export.csv?plan=quote",
                           headers=sales)
    names = [r[1] for r in csv.reader(io.StringIO(res.text))][1:]
    assert "Bank build (idea)" in names
    assert not any("(idea) (idea)" in n for n in names)
    await _task(client, sales, cid, "Spare", "2026-11-02", 1, is_idea=True)
    res = await client.get(f"/api/v1/changes/{cid}/plan/export.csv?plan=quote",
                           headers=sales)
    assert "Spare (idea)" in [r[1] for r in csv.reader(io.StringIO(res.text))]


async def test_schedule_after_baseline_needs_a_reason(client, world, session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    t = _by_name(await _plan(client, sales, cid, "detailed"))
    val = t["Measurement and validation"]
    # an admin fix in the database: validation starts 3 days too early
    async with session_factory() as s:
        row = await s.get(ChangePlanTask, val["id"])
        row.start_date = row.start_date - timedelta(days=3)
        await s.commit()
    url = f"/api/v1/changes/{cid}/plan/schedule"
    res = await client.post(url, json={"plan": "detailed"}, headers=sales)
    assert res.status_code == 400 and "reason" in res.json()["detail"]
    res = await client.post(url, json={"plan": "detailed", "reason": "re-plan"},
                            headers=sales)
    assert res.status_code == 200, res.text
    devs = (await client.get(f"/api/v1/changes/{cid}/plan/deviations",
                             headers=sales)).json()
    assert [(x["task_name"], x["reason"], x["caused_by_task_id"]) for x in devs] == [
        ("Measurement and validation", "re-plan", None)]
    assert devs[0]["new_start"] == val["start_date"]


async def test_import_warnings_and_refusals(client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    url = f"/api/v1/changes/{cid}/plan/import"
    xml = (
        '<?xml version="1.0"?><Project xmlns="http://schemas.microsoft.com/project">'
        '<DurationFormat>7</DurationFormat><Tasks>'
        '<Task><UID>1</UID><Name>A</Name><Start>2026-10-05T08:00:00</Start>'
        '<Duration>PT16H0M0S</Duration><OutlineLevel>1</OutlineLevel>'
        '<PercentComplete>30</PercentComplete>'
        '<PredecessorLink><PredecessorUID>9</PredecessorUID><CrossProject>1'
        '</CrossProject></PredecessorLink></Task></Tasks></Project>')
    res = await client.post(url, data={"plan": "quote"},
                            files={"file": ("p.xml", xml.encode(), "application/xml")},
                            headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    assert len(out["import_warnings"]) == 1 and "another project" in \
        out["import_warnings"][0]
    assert _by_name(out)["A"]["progress_pct"] == 30
    # a summary with a must-start-on is refused, the plan stays as it was
    bad = xml.replace(
        '<PercentComplete>30</PercentComplete>',
        '<ConstraintType>2</ConstraintType>'
        '<ConstraintDate>2026-10-05T08:00:00</ConstraintDate>').replace(
        '</Task></Tasks>', '</Task><Task><UID>2</UID><Name>B</Name>'
        '<Start>2026-10-05T08:00:00</Start><Duration>PT8H0M0S</Duration>'
        '<OutlineLevel>2</OutlineLevel></Task></Tasks>')
    res = await client.post(url, data={"plan": "quote"},
                            files={"file": ("p.xml", bad.encode(), "application/xml")},
                            headers=sales)
    assert res.status_code == 400 and "summary" in res.json()["detail"]
    assert len((await _plan(client, sales, cid))["tasks"]) == 1
    # an import into the detailed plan does not change the quote calendar
    await _set(session_factory, cid, status="approved")
    elapsed = xml.replace("<DurationFormat>7</DurationFormat>",
                          "<DurationFormat>8</DurationFormat>")
    res = await client.post(url, data={"plan": "detailed"},
                            files={"file": ("p.xml", elapsed.encode(),
                                            "application/xml")},
                            headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["calendar"]["mode"] == "calendar"
    assert (await _plan(client, sales, cid, "quote"))["calendar"]["mode"] == "working"
