"""Plan polish B2: deviation groups (one edit, one decision), actual dates
in order, the quote plan frozen once the offer is accepted, dates in
messages as the user reads them, the recovery card's plan finish and a
passed validation check without a stale note.

The world, helpers and baseline come from test_change_plan (only the
underscore helpers and the fixture are imported: no test is collected twice).
"""
from datetime import date, timedelta
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import select

from app.core.display import fmt_date
from app.models.change import ChangeRequest
from app.models.change_plan import ChangePlanDeviation, ChangePlanDeviationGroup
from app.services.change_plan_service import ChangePlanService, validate_plan
from tests.test_change_plan import (  # noqa: F401  (world is a fixture)
    NS, _approved_with_detailed, _auth, _baselined, _by_name, _plan, _seed, _set,
    _today, world,
)
from tests.test_validation_checks import (  # noqa: F401  (val is a fixture)
    _check as _vcheck, _state as _vstate, val,
)

pytestmark = pytest.mark.asyncio


async def _devs(client, cid, auth):
    res = await client.get(f"/api/v1/changes/{cid}/plan/deviations", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _move_impl(client, cid, sales, days=25, reason="supplier late"):
    t = _by_name(await _plan(client, sales, cid, "detailed"))
    impl = t["Implementation"]
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{impl['id']}",
                             json={"duration_days": days, "reason": reason},
                             headers=sales)
    assert res.status_code == 200, res.text
    return impl


# --- deviation groups ------------------------------------------------------

async def test_one_move_is_one_group_and_counts_once(client, world, session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    impl = await _move_impl(client, cid, sales)
    devs = await _devs(client, cid, sales)
    assert len(devs) > 1
    gids = {d["group_id"] for d in devs}
    assert len(gids) == 1 and None not in gids
    async with session_factory() as s:
        g = await s.get(ChangePlanDeviationGroup, gids.pop())
        assert (g.root_task_id, g.reason, g.status) == (
            impl["id"], "supplier late", "open")
        change = await s.get(ChangeRequest, cid)
        assert await ChangePlanService.open_deviation_count(s, change) == 1
    # my-actions says one decision, not one per pushed row
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                             headers=sales)).json()["actions"]
    dev = next(a for a in acts if a["kind"] == "plan_deviation")
    assert dev["count"] == 1

    # a second move is a second group; a legacy row without group counts alone
    await _move_impl(client, cid, sales, days=27, reason="again")
    async with session_factory() as s:
        row = (await s.execute(select(ChangePlanDeviation)
                               .order_by(ChangePlanDeviation.id))).scalars().first()
        s.add(ChangePlanDeviation(
            change_id=cid, task_id=row.task_id, old_start=row.old_start,
            old_end=row.old_end, new_start=row.new_start, new_end=row.new_end,
            reason="legacy", status="open", created_by=row.created_by))
        s.add(ChangePlanDeviation(
            change_id=cid, task_id=row.task_id, old_start=row.old_start,
            old_end=row.old_end, new_start=row.new_start, new_end=row.new_end,
            reason="legacy 2", status="open", created_by=row.created_by))
        await s.commit()
        change = await s.get(ChangeRequest, cid)
        assert await ChangePlanService.open_deviation_count(s, change) == 4


async def test_group_lock_decides_every_open_row_at_once(client, world, session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    await _move_impl(client, cid, sales)
    devs = await _devs(client, cid, sales)
    gid = devs[0]["group_id"]
    url = f"/api/v1/changes/{cid}/plan/deviations/groups/{gid}"
    # same rights as a single row
    res = await client.post(f"{url}/lock", json={},
                            headers=await _auth(client, "pack"))
    assert res.status_code == 403
    # an unknown group is a 404
    res = await client.post(
        f"/api/v1/changes/{cid}/plan/deviations/groups/99999/lock", json={},
        headers=sales)
    assert res.status_code == 404
    # one row decided on its own first: the group lock takes the rest
    first = devs[-1]["id"]
    res = await client.post(f"/api/v1/changes/{cid}/plan/deviations/{first}/lock",
                            json={"note": "alone"}, headers=sales)
    assert res.status_code == 200, res.text
    res = await client.post(f"{url}/lock", json={"note": "absorbed"},
                            headers=await _auth(client, "pm"))
    assert res.status_code == 200, res.text
    out = res.json()
    assert len(out) == len(devs) and all(d["status"] == "locked" for d in out)
    notes = {d["id"]: d["decision_note"] for d in out}
    assert notes.pop(first) == "alone"
    assert set(notes.values()) == {"absorbed"}
    # nothing left to decide
    res = await client.post(f"{url}/lock", json={}, headers=sales)
    assert res.status_code == 400 and "already decided" in res.json()["detail"]
    async with session_factory() as s:
        g = await s.get(ChangePlanDeviationGroup, gid)
        assert g.status == "locked" and g.decision_note == "absorbed"
    log = (await client.get(f"/api/v1/changes/{cid}/changelog",
                            headers=sales)).json()
    locked = [e for e in log if e["action"] == "deviation_locked"]
    assert len(locked) == 2           # the single row, then the group once


async def test_group_escalate_shares_one_escalation(client, world, session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    await _move_impl(client, cid, sales)
    devs = await _devs(client, cid, sales)
    gid = devs[0]["group_id"]
    url = f"/api/v1/changes/{cid}/plan/deviations/groups/{gid}/escalate"
    res = await client.post(url, json={"note": "  "}, headers=sales)
    assert res.status_code == 400
    res = await client.post(url, json={"note": "customer told +5 days"},
                            headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    assert all(d["status"] == "escalated" for d in out)
    esc_ids = {d["escalation_id"] for d in out}
    assert len(esc_ids) == 1 and None not in esc_ids
    esc = (await client.get(f"/api/v1/changes/{cid}/implementation/escalations",
                            headers=sales)).json()
    assert [e["id"] for e in esc] == list(esc_ids)
    log = (await client.get(f"/api/v1/changes/{cid}/changelog",
                            headers=sales)).json()
    escalated = [e for e in log if e["action"] == "deviation_escalated"]
    assert len(escalated) == 1
    async with session_factory() as s:
        g = await s.get(ChangePlanDeviationGroup, gid)
        assert g.status == "escalated" and g.escalation_id in esc_ids


async def test_group_decision_window(client, world, session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    await _move_impl(client, cid, sales)
    gid = (await _devs(client, cid, sales))[0]["group_id"]
    await _set(session_factory, cid, status="released")
    res = await client.post(
        f"/api/v1/changes/{cid}/plan/deviations/groups/{gid}/lock", json={},
        headers=sales)
    assert res.status_code == 400
    assert all(d["status"] == "open" for d in await _devs(client, cid, sales))


async def test_rows_decided_one_by_one_settle_their_group(
        client, world, session_factory):
    cid, sales = await _baselined(client, world, session_factory)
    await _move_impl(client, cid, sales)
    devs = await _devs(client, cid, sales)
    gid = devs[0]["group_id"]
    *rest, last = devs
    for d in rest:
        res = await client.post(
            f"/api/v1/changes/{cid}/plan/deviations/{d['id']}/lock", json={},
            headers=sales)
        assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangePlanDeviationGroup, gid)).status == "open"
    res = await client.post(
        f"/api/v1/changes/{cid}/plan/deviations/{last['id']}/escalate",
        json={"note": "this one to the customer"}, headers=sales)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangePlanDeviationGroup, gid)).status == "mixed"


# --- actual dates -----------------------------------------------------------

async def test_actual_finish_not_before_actual_start(client, world, session_factory):
    cid, sales = await _approved_with_detailed(client, world, session_factory)
    await _set(session_factory, cid, status="in_implementation")
    tool = await _auth(client, "tool")
    impl = _by_name(await _plan(client, tool, cid, "detailed"))["Implementation"]
    url = f"/api/v1/changes/{cid}/plan/tasks/{impl['id']}"
    res = await client.patch(url, json={"actual_start": _today(-3),
                                        "actual_finish": _today(-5)}, headers=tool)
    assert res.status_code == 400
    assert "before its actual start" in res.json()["detail"]
    res = await client.patch(url, json={"actual_start": _today(-3)}, headers=tool)
    assert res.status_code == 200, res.text
    # the stored start counts when only the finish is sent
    res = await client.patch(url, json={"actual_finish": _today(-4)}, headers=tool)
    assert res.status_code == 400
    assert fmt_date(date.fromisoformat(_today(-4))) in res.json()["detail"]
    # one day of slack stays, and the same day is fine
    res = await client.patch(url, json={"actual_finish": _today(1)}, headers=tool)
    assert res.status_code == 200, res.text
    res = await client.patch(url, json={"actual_finish": _today(-3)}, headers=tool)
    assert res.status_code == 200, res.text
    # future: the message reads as a date, not ISO
    res = await client.patch(url, json={"actual_start": _today(3)}, headers=tool)
    assert res.status_code == 400
    assert fmt_date(date.fromisoformat(_today(3))) in res.json()["detail"]


async def test_import_drops_an_actual_finish_before_its_start(
        client, world, session_factory):
    cid, sales = await _approved_with_detailed(client, world, session_factory)
    await _set(session_factory, cid, status="in_implementation")
    xml = (await client.get(f"/api/v1/changes/{cid}/plan/export.xml?plan=detailed",
                            headers=sales)).content
    ET.register_namespace("", NS.strip("{}"))
    root = ET.fromstring(xml)
    task = next(t for t in root.iter(f"{NS}Task")
                if t.find(f"{NS}Name").text == "Implementation")
    for tag, day in (("ActualStart", _today(-2)), ("ActualFinish", _today(-6))):
        el = task.find(f"{NS}{tag}")
        if el is None:
            el = ET.SubElement(task, f"{NS}{tag}")
        el.text = f"{day}T08:00:00"
    body = ET.tostring(root)
    res = await client.post(f"/api/v1/changes/{cid}/plan/import",
                            data={"plan": "detailed", "replace": "true"},
                            files={"file": ("p.xml", body, "application/xml")},
                            headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    assert any("before its actual start" in w for w in out["import_warnings"])
    impl = _by_name(out)["Implementation"]
    assert impl["actual_start"] == _today(-2) and impl["actual_finish"] is None


# --- quote plan frozen once the offer is accepted ---------------------------

async def test_quote_plan_read_only_after_acceptance(client, world, session_factory):
    cid = world["change_id"]
    sales = await _auth(client, "sales")
    assert (await _seed(client, sales, cid)).status_code == 200
    await _set(session_factory, cid, status="quoted")
    assert (await _plan(client, sales, cid))["can_edit"] is True
    await _set(session_factory, cid, customer_response="accepted")
    out = await _plan(client, sales, cid)
    assert out["can_edit"] is False and out["can_edit_dates"] is False
    t = out["tasks"][0]
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{t['id']}",
                             json={"duration_days": 9}, headers=sales)
    assert res.status_code == 400
    assert "accepted the offer" in res.json()["detail"]
    res = await client.post(f"/api/v1/changes/{cid}/plan/tasks", json={
        "plan": "quote", "name": "late", "start_date": "2026-11-01"}, headers=sales)
    assert res.status_code == 400 and "accepted the offer" in res.json()["detail"]
    res = await client.put(f"/api/v1/changes/{cid}/plan/calendar?plan=quote",
                           json={"mode": "working"}, headers=sales)
    assert res.status_code in (400, 405, 422)
    # an accepted offer id alone is enough
    await _set(session_factory, cid, customer_response="pending", accepted_offer_id=1)
    res = await client.patch(f"/api/v1/changes/{cid}/plan/tasks/{t['id']}",
                             json={"duration_days": 9}, headers=sales)
    assert res.status_code == 400 and "accepted the offer" in res.json()["detail"]


async def test_window_helpers():
    c = SimpleNamespace(status="quoted", accepted_offer_id=None,
                        customer_response="negotiating")
    assert ChangePlanService.in_window(c, "quote")
    assert not ChangePlanService.in_window(c, "detailed")
    c.customer_response = "accepted"
    assert not ChangePlanService.in_window(c, "quote")
    c.status = "approved"
    assert ChangePlanService.in_window(c, "detailed")


# --- user-facing dates ------------------------------------------------------

async def test_plan_warnings_show_readable_dates():
    def t(i, name, kind, start, dur, **kw):
        return SimpleNamespace(
            id=i, name=name, kind=kind, lane="Sales", department_id=None,
            is_idea=kw.get("idea", False), start_date=start, duration_days=dur,
            end_date=start + timedelta(days=dur), parent_id=None,
            predecessors=[], constraint_type=None, constraint_date=None,
            actual_start=None, sort_order=i)
    d0 = date(2026, 11, 2)
    tasks = [t(1, "Build", "bank_build", d0, 10),
             t(2, "Stop", "downtime", d0 + timedelta(days=3), 2)]
    out = validate_plan(tasks, plan="quote", release_due=d0)
    msgs = " ".join(w["message"] for w in out["warnings"])
    assert fmt_date(d0) in msgs and d0.isoformat() not in msgs
    assert fmt_date(d0 + timedelta(days=3)) in msgs


# --- recovery card plan finish -----------------------------------------------

async def test_recovery_info_counts_a_milestone_on_its_day():
    from app.services.validation_issue_service import ValidationIssueService as V

    def t(i, start, dur, parent=None, base=None):
        end = start + timedelta(days=dur)
        return SimpleNamespace(
            id=i, start_date=start, duration_days=dur, end_date=end,
            parent_id=parent, is_idea=False,
            baseline_start=base[0] if base else None,
            baseline_finish=base[1] if base else None)
    d = date(2026, 11, 2)
    group = t(1, d, 6)
    work = t(2, d, 5, parent=1)
    ms = t(3, d + timedelta(days=5), 0, parent=1)          # milestone last
    ctx = {"by_id": {1: group, 2: work, 3: ms},
           "finish": d + timedelta(days=5), "baseline": d + timedelta(days=3)}
    issue = SimpleNamespace(recovery_task_id=1, revalidation_task_id=None)
    change = SimpleNamespace(release_due_date=None)
    rec = V.recovery_info(change, issue, ctx)
    # the milestone sits on its own day; the old "end minus one" said d+4
    assert rec["finish"] == d + timedelta(days=5)
    assert rec["plan_finish"] == d + timedelta(days=5)
    assert rec["slip_days"] == 2


async def test_plan_context_uses_the_plan_finish(monkeypatch):
    from app.services import validation_issue_service as vis
    d = date(2026, 11, 2)
    work = SimpleNamespace(id=1, name="Work", start_date=d, duration_days=5,
                           end_date=d + timedelta(days=5), parent_id=None,
                           is_idea=False, baseline_start=d,
                           baseline_finish=d + timedelta(days=4))
    ms = SimpleNamespace(id=2, name="SOP", start_date=d + timedelta(days=6), duration_days=0,
                         end_date=d + timedelta(days=6), parent_id=None,
                         is_idea=False, baseline_start=d + timedelta(days=5),
                         baseline_finish=d + timedelta(days=5))

    async def tasks(session, change, plan):
        return [work, ms]
    monkeypatch.setattr(ChangePlanService, "tasks", staticmethod(tasks))
    ctx = await vis.ValidationIssueService.plan_context(
        None, SimpleNamespace(plan_calendar=None))
    assert ctx["finish"] == d + timedelta(days=6)        # milestone day
    assert ctx["baseline"] == d + timedelta(days=5)


# --- validation check note ---------------------------------------------------

async def test_passing_a_check_clears_the_failure_note(client, admin_auth, val):
    """The note explained the failure; passing without a new note drops it,
    passing with one keeps the new one, a re-pass keeps what is there."""
    async def note():
        state = await _vstate(client, admin_auth, val)
        dev = next(d for d in state["departments"]
                   if d["department_name"] == "Development")
        return next(c for c in dev["checks"]
                    if c["check_key"] == "revision_bump")["note"]
    res = await _vcheck(client, admin_auth, val, "Development", "revision_bump",
                        status="failed", note="customer statement says rev D")
    assert res.status_code == 201, res.text
    assert await note() == "customer statement says rev D"
    res = await _vcheck(client, admin_auth, val, "Development", "revision_bump")
    assert res.status_code == 201, res.text
    assert await note() is None
    await _vcheck(client, admin_auth, val, "Development", "revision_bump",
                  status="failed", note="again")
    await _vcheck(client, admin_auth, val, "Development", "revision_bump",
                  note="rev E confirmed")
    assert await note() == "rev E confirmed"
    await _vcheck(client, admin_auth, val, "Development", "revision_bump")
    assert await note() == "rev E confirmed"
