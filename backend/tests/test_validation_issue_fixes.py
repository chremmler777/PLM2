"""Validation issues: fixes from the 2dd5ed3c review (B1-B3, B5-B9, B11).

new_timing deadline at end of day with the reason kept; extra cost after
close; recovery blocks done on close; a concession accepted before its route;
the customer mail of an accepted concession frozen; escalation audience and
references limited to the change's organization; a re-check passed early;
the sweep's system marker and per-change isolation; four eyes on the
acknowledgement; a second recovery in parallel; an act for every state.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.utils.clock import business_today
from app.auth.security import get_password_hash
from app.models.change import ChangeChangelog, ChangeRequest
from app.models.change_plan import ChangePlanLink, ChangePlanTask
from app.models.change_validation import ValidationCheck
from app.models.change_validation_issue import ValidationIssue
from app.models.entities import Organization, Plant, Project, User
from app.models.notification import Notification
from app.models.part import Part
from app.models.workflow import Department, UserDepartment
from app.services.validation_issue_service import ValidationIssueService
from tests.conftest import ENGINEER_PASSWORD
from tests.test_validation_issues import (  # noqa: F401  (fixtures)
    TODAY, _auth, _backdate_issue, _changelog, _make, _raised, _ready, _route,
    _tasks, _upload, _url, vi, vib,
)

pytestmark = pytest.mark.asyncio


async def _answer(session_factory, vi, status):
    """Answer the failed check again through the issue hook."""
    async with session_factory() as s:
        chk = await s.get(ValidationCheck, vi["check_id"])
        chk.status = status
        change = await s.get(ChangeRequest, vi["change_id"])
        u = await s.get(User, vi["user"]["tool"]["id"])
        res = await ValidationIssueService.on_check_answered(s, change, chk, u)
        await s.commit()
    return res


async def _other_org(session_factory, *, dept=None, role="engineer", key="x"):
    """A user of another organization (optionally in a department by name)."""
    async with session_factory() as s:
        org = Organization(name=f"Other {key}", code=f"other-{key}", is_active=True)
        s.add(org)
        await s.flush()
        u = User(organization_id=org.id, username=f"{key}-other",
                 email=f"{key}@other.test", full_name=f"Other {key}", role=role,
                 hashed_password=get_password_hash(ENGINEER_PASSWORD),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        if dept:
            d = (await s.execute(select(Department).where(
                Department.name == dept).limit(1))).scalar_one()
            s.add(UserDepartment(user_id=u.id, department_id=d.id))
        plant = Plant(organization_id=org.id, name="P2", code=f"p2-{key}",
                      location="FR", is_active=True)
        s.add(plant)
        await s.flush()
        proj = Project(plant_id=plant.id, name="Other project", code=f"op-{key}")
        s.add(proj)
        await s.flush()
        part = Part(project_id=proj.id, part_number=f"OTHER-{key}", name="Other part",
                    part_type="internal_mfg", created_by=u.id)
        s.add(part)
        await s.commit()
        return {"user_id": u.id, "org_id": org.id, "part_id": part.id}


# --- B1 new timing --------------------------------------------------------------

async def test_new_timing_end_of_day_keeps_reason_refuses_past(client, session_factory, seed):
    vi = await _make(session_factory, seed, baseline=True,
                     release_due=TODAY + timedelta(days=5))
    async with session_factory() as s:
        c = await s.get(ChangeRequest, vi["change_id"])
        c.release_due_reason = "Customer SOP"
        await s.commit()
    issue = await _raised(client, vi)
    await _ready(client, vi, issue["id"])
    assert (await _route(client, vi, issue["id"], who="lead")).status_code == 200
    sales = await _auth(client, vi, "sales")
    r = await client.post(_url(vi, f"/{issue['id']}/customer"), headers=sales,
                          json={"decision": "new_timing", "note": "Late",
                                "new_date": (TODAY - timedelta(days=1)).isoformat()})
    assert r.status_code == 400 and "past" in r.json()["detail"]
    new = TODAY + timedelta(days=60)
    r = await client.post(_url(vi, f"/{issue['id']}/customer"), headers=sales,
                          json={"decision": "new_timing", "note": "New SOP agreed",
                                "new_date": new.isoformat()})
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        c = await s.get(ChangeRequest, vi["change_id"])
        assert c.release_due_date == datetime.combine(new, datetime.min.time()).replace(
            hour=23, minute=59, second=59)
        assert c.release_due_reason == "Customer SOP; VI-1: New SOP agreed"


# --- B2 extra cost after close --------------------------------------------------

async def test_extra_cost_editable_after_close_audited(client, vi, session_factory):
    issue = await _raised(client, vi)
    iid = issue["id"]
    await _ready(client, vi, iid)
    r = await _route(client, vi, iid, route="follow_up_change", actions=[])
    assert r.status_code == 200 and r.json()["status"] == "transferred"
    pm = await _auth(client, vi, "pm")
    assert "cost" in r.json()["extra_acts"]
    tool = await _auth(client, vi, "tool")
    assert (await client.post(_url(vi, f"/{iid}/cost"), headers=tool,
                              json={"extra_cost": 5, "cost_bearer": "internal"})
            ).status_code == 403
    r = await client.post(_url(vi, f"/{iid}/cost"), headers=pm,
                          json={"extra_cost": 500, "cost_bearer": "customer"})
    assert r.status_code == 200, r.text
    assert r.json()["extra_cost"] == 500
    # the quote of the fix still lands after close too (Sales)
    sales = await _auth(client, vi, "sales")
    view = (await client.get(_url(vi, f"/{iid}"), headers=sales)).json()
    assert "quote_fix" in view["extra_acts"]
    assert (await client.post(_url(vi, f"/{iid}/fix-quoted"), headers=sales,
                              json={})).status_code == 200
    rows = [e for e in await _changelog(session_factory, vi["change_id"])
            if e.action == "validation_issue_cost"]
    assert rows and '"after_close": true' in rows[-1].new_value
    assert "after the issue was transferred" in rows[-1].action_description


# --- B3 recovery blocks done on close ---------------------------------------------

async def test_close_marks_recovery_blocks_done(client, vi, session_factory):
    issue = await _raised(client, vi)
    iid = issue["id"]
    await _ready(client, vi, iid)
    out = (await _route(client, vi, iid)).json()
    aid = out["actions"][0]["id"]
    fix_block = out["actions"][0]["plan_task_id"]
    rv_block = out["recovery"]["revalidation_task_id"]
    pm = await _auth(client, vi, "pm")
    assert (await client.post(_url(vi, f"/{iid}/actions/{aid}/done"),
                              headers=pm)).status_code == 200
    res = await _answer(session_factory, vi, "passed")
    assert res["closed"] == [iid]
    tasks = await _tasks(session_factory, vi["change_id"])
    for tid in (fix_block, rv_block):
        t = tasks[tid]
        assert t.progress_pct == 100
        assert t.actual_finish == business_today()
        assert t.actual_start is not None and t.actual_start <= t.actual_finish
    closed = [e for e in await _changelog(session_factory, vi["change_id"])
              if e.action == "validation_issue_closed"]
    assert "plan_task_ids_done" in closed[-1].new_value


# --- B5 concession accepted before its route ---------------------------------------

async def _pre_accept(client, vi, *, mail: bool):
    issue = await _raised(client, vi, check_id=None, category="cosmetic",
                          department_id=vi["dept"]["Tool Engineer"])
    iid = issue["id"]
    sales = await _auth(client, vi, "sales")
    r = await client.patch(_url(vi, f"/{iid}"), headers=sales,
                           json={"customer_inform": True})
    assert r.status_code == 200, r.text
    if mail:
        assert (await _upload(client, sales, vi, iid)).status_code == 201
    r = await client.post(_url(vi, f"/{iid}/customer"), headers=sales,
                          json={"decision": "accept_deviation", "note": "ok as is"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open"
    return iid, sales


async def test_concession_after_accept_with_mail_closes(client, vi):
    iid, sales = await _pre_accept(client, vi, mail=True)
    r = await _route(client, vi, iid, route="customer_concession", actions=[])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"
    assert r.json()["closure_note"] == "ok as is"


async def test_concession_after_accept_without_mail_gives_sales_the_act(client, vi):
    iid, sales = await _pre_accept(client, vi, mail=False)
    r = await _route(client, vi, iid, route="customer_concession", actions=[])
    assert r.status_code == 200 and r.json()["status"] == "route_decided"
    view = (await client.get(_url(vi, f"/{iid}"), headers=sales)).json()
    assert view["primary_act"] == "customer"
    mine = (await client.get(f"/api/v1/changes/{vi['change_id']}/my-actions",
                             headers=sales)).json()
    rows = mine if isinstance(mine, list) else mine.get("actions", [])
    assert any(a["kind"] == "validation_issue_customer" for a in rows)
    assert (await _upload(client, sales, vi, iid)).status_code == 201
    r = await client.post(_url(vi, f"/{iid}/customer"), headers=sales,
                          json={"decision": "accept_deviation", "note": "mail filed"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"


# --- B6 the customer mail of an accepted concession ---------------------------------

async def test_mail_of_accepted_concession_is_frozen(client, vi):
    iid, sales = await _pre_accept(client, vi, mail=True)
    r = await _route(client, vi, iid, route="customer_concession", actions=[])
    assert r.json()["status"] == "accepted"
    att = r.json()["attachments"][0]
    view = (await client.get(_url(vi, f"/{iid}"), headers=sales)).json()
    assert view["attachments"][0]["can_delete"] is False
    url = f"/api/v1/changes/{vi['change_id']}/attachments/{att['id']}"
    assert (await client.delete(url, headers=sales)).status_code == 409
    pm = await _auth(client, vi, "pm")
    assert (await client.delete(url, headers=pm)).status_code == 409
    admin = await _auth(client, vi, "admin")
    assert (await client.get(_url(vi, f"/{iid}"), headers=admin)).json()[
        "attachments"][0]["can_delete"] is True
    assert (await client.delete(url, headers=admin)).status_code == 204


async def test_evidence_of_an_open_issue_stays_deletable(client, vi):
    issue = await _raised(client, vi, check_id=None, category="cosmetic")
    sales = await _auth(client, vi, "sales")
    att = (await _upload(client, sales, vi, issue["id"], kind="general")).json()
    view = (await client.get(_url(vi, f"/{issue['id']}"), headers=sales)).json()
    assert view["attachments"][0]["can_delete"] is True
    r = await client.delete(
        f"/api/v1/changes/{vi['change_id']}/attachments/{att['id']}", headers=sales)
    assert r.status_code == 204


# --- B7 escalation audience in the change's organization -----------------------------

async def test_escalation_audience_is_the_changes_organization(client, vi, session_factory):
    other_pm = await _other_org(session_factory, dept="Project Manager", key="pm")
    other_admin = await _other_org(session_factory, role="admin", key="adm")
    issue = await _raised(client, vi)
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{issue['id']}/escalate"), headers=pm,
                          json={"reason": "Customer line stop", "level": 3})
    assert r.status_code == 200, r.text
    assert "admins" in r.json()["escalation"]["latest"]["notified"]
    async with session_factory() as s:
        got = set((await s.execute(select(Notification.user_id))).scalars().all())
    assert other_pm["user_id"] not in got
    assert other_admin["user_id"] not in got
    assert vi["admin_id"] in got                 # the change's own org admin
    assert vi["user"]["pm2"]["id"] in got


# --- B8 references of the change's organization ---------------------------------------

async def test_part_and_owner_of_another_org_refused(client, vi, session_factory):
    other = await _other_org(session_factory, key="ref")
    tool = await _auth(client, vi, "tool")
    r = await client.post(_url(vi), headers=tool, json={
        "title": "x", "description": "y", "check_id": vi["check_id"],
        "affected_part_id": other["part_id"]})
    assert r.status_code == 400 and "organization" in r.json()["detail"]
    r = await client.post(_url(vi), headers=tool, json={
        "title": "x", "description": "y", "check_id": vi["check_id"],
        "affected_part_id": 999999})
    assert r.status_code == 400
    issue = await _raised(client, vi)
    r = await client.patch(_url(vi, f"/{issue['id']}"), headers=tool,
                           json={"affected_part_id": other["part_id"]})
    assert r.status_code == 400
    await _ready(client, vi, issue["id"])
    r = await _route(client, vi, issue["id"], actions=[
        {"description": "Fix", "owner_id": other["user_id"]}])
    assert r.status_code == 400 and "organization" in r.json()["detail"]
    r = await _route(client, vi, issue["id"], actions=[
        {"description": "Fix", "owner_id": vi["user"]["dev"]["id"]}])
    assert r.status_code == 200, r.text


# --- B9 a re-check passed while fix actions are open ---------------------------------

async def test_early_pass_keeps_open_until_actions_done(client, vi, session_factory):
    issue = await _raised(client, vi)
    iid = issue["id"]
    await _ready(client, vi, iid)
    out = (await _route(client, vi, iid)).json()
    aid = out["actions"][0]["id"]
    res = await _answer(session_factory, vi, "passed")
    assert res["closed"] == [] and res["revalidated_early"] == [iid]
    pm = await _auth(client, vi, "pm")
    assert (await client.get(_url(vi, f"/{iid}"), headers=pm)).json()["status"] == "fixing"
    r = await client.post(_url(vi, f"/{iid}/actions/{aid}/done"), headers=pm)
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert r.json()["closure_note"] == "Re-validated: the linked check passed"
    actions = [e.action for e in await _changelog(session_factory, vi["change_id"])]
    assert "validation_issue_revalidated_early" in actions


# --- B5 an act for every state -------------------------------------------------------

async def test_revalidation_and_refixing_have_an_owner(client, vi, session_factory):
    issue = await _raised(client, vi)
    iid = issue["id"]
    await _ready(client, vi, iid)
    out = (await _route(client, vi, iid)).json()
    aid = out["actions"][0]["id"]
    tool = await _auth(client, vi, "tool")
    await client.post(_url(vi, f"/{iid}/actions/{aid}/done"), headers=tool)
    # the check is answered again in validation, not while implementing
    from app.models.change import ChangeRequest
    for status, offered in (("in_implementation", False), ("in_validation", True)):
        async with session_factory() as s:
            (await s.get(ChangeRequest, vi["change_id"])).status = status
            await s.commit()
        view = (await client.get(_url(vi, f"/{iid}"), headers=tool)).json()
        assert view["status"] == "revalidation"
        assert (view["primary_act"] == "recheck") is offered
        assert ("recheck" in view["next_acts"]) is offered
        assert (view["step_note"] is None) is offered
        rows = (await client.get(f"/api/v1/changes/{vi['change_id']}/my-actions",
                                 headers=tool)).json()
        rows = rows if isinstance(rows, list) else rows.get("actions", [])
        assert ("validation_issue_recheck" in [a["kind"] for a in rows]) is offered
    # the re-check fails again with every action done: a new action is next
    await _answer(session_factory, vi, "failed")
    view = (await client.get(_url(vi, f"/{iid}"), headers=tool)).json()
    assert view["status"] == "fixing" and view["primary_act"] == "add_action"
    rows = (await client.get(f"/api/v1/changes/{vi['change_id']}/my-actions",
                             headers=tool)).json()
    rows = rows if isinstance(rows, list) else rows.get("actions", [])
    assert "validation_issue_add_action" in [a["kind"] for a in rows]


# --- B11 --------------------------------------------------------------------------------

async def test_sweep_entries_carry_the_system_marker(client, vi, session_factory):
    from app.services.notification_sweep import run_notification_sweep
    issue = await _raised(client, vi)
    await _backdate_issue(session_factory, issue["id"], 7)
    async with session_factory() as s:
        await run_notification_sweep(s)
        await s.commit()
    rows = [e for e in await _changelog(session_factory, vi["change_id"])
            if e.action == "validation_issue_escalated"]
    auto = rows[-1]
    assert '"system": true' in auto.new_value
    assert auto.action_description.endswith("(automatic)")
    # a person's entry has no marker
    assert '"system"' not in rows[0].new_value


async def test_sweep_isolates_a_failing_change(client, vi, session_factory, seed,
                                               monkeypatch):
    issue = await _raised(client, vi)
    await _backdate_issue(session_factory, issue["id"], 7)
    async with session_factory() as s:
        bad = ChangeRequest(change_number="C-VI-BAD", title="Bad", reason="r",
                            change_type="physical_part", project_id=seed["project_id"],
                            raised_by=seed["admin_id"], status="in_validation",
                            customer_relevant=True)
        s.add(bad)
        await s.flush()
        s.add(ValidationIssue(change_id=bad.id, number=1, title="t", category="other",
                              severity=2, description="d", status="open",
                              escalation_level=1, created_by=seed["admin_id"],
                              created_at=datetime.utcnow() - timedelta(days=9),
                              updated_at=datetime.utcnow()))
        await s.commit()
        bad_id = bad.id
    orig = ValidationIssueService.reevaluate

    async def boom(session, change, *a, **kw):
        if change.id == bad_id:
            raise RuntimeError("broken change")
        return await orig(session, change, *a, **kw)
    monkeypatch.setattr(ValidationIssueService, "reevaluate", staticmethod(boom))
    async with session_factory() as s:
        assert await ValidationIssueService.reevaluate_all(s) == 1
        await s.commit()
    async with session_factory() as s:
        assert (await s.get(ValidationIssue, issue["id"])).escalation_level == 2


async def test_raiser_of_an_escalation_cannot_acknowledge_it(client, vi):
    issue = await _raised(client, vi)
    iid = issue["id"]
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{iid}/escalate"), headers=pm,
                          json={"reason": "Slow", "level": 2})
    esc = r.json()["escalation"]["latest"]
    assert esc["can_acknowledge"] is False
    assert "acknowledge" not in r.json()["next_acts"]
    url = _url(vi, f"/{iid}/escalations/{esc['id']}/acknowledge")
    assert (await client.post(url, headers=pm)).status_code == 403
    pm2 = await _auth(client, vi, "pm2")
    view = (await client.get(_url(vi, f"/{iid}"), headers=pm2)).json()
    assert view["escalation"]["latest"]["can_acknowledge"] is True
    assert (await client.post(url, headers=pm2)).status_code == 200


async def test_second_recovery_runs_in_parallel(client, vi, session_factory):
    i1 = await _raised(client, vi)
    await _ready(client, vi, i1["id"])
    r1 = (await _route(client, vi, i1["id"])).json()
    i2 = await _raised(client, vi, check_id=None, title="Second", description="x",
                       department_id=vi["dept"]["Tool Engineer"])
    await _ready(client, vi, i2["id"])
    r2 = await _route(client, vi, i2["id"])
    assert r2.status_code == 200, r2.text
    r2 = r2.json()
    tasks = await _tasks(session_factory, vi["change_id"])
    s1, s2 = r1["recovery"]["summary_task_id"], r2["recovery"]["summary_task_id"]
    rv1, rv2 = r1["recovery"]["revalidation_task_id"], r2["recovery"]["revalidation_task_id"]
    assert tasks[s2].start_date == tasks[s1].start_date       # not after VI-1
    async with session_factory() as s:
        links = {(lk.from_task_id, lk.to_task_id) for lk in (await s.execute(
            select(ChangePlanLink).where(
                ChangePlanLink.change_id == vi["change_id"]))).scalars().all()}
    v, c = vi["tasks"]["V"], vi["tasks"]["C"]
    assert (v, s2) in links and (rv2, c) in links
    assert (rv1, s2) not in links and (rv2, s1) not in links
    assert not any(f in (rv1, s1) and t == s2 for f, t in links)


async def test_recovery_finish_is_its_blocks_last_day(client, vi, session_factory):
    issue = await _raised(client, vi)
    await _ready(client, vi, issue["id"])
    out = (await _route(client, vi, issue["id"])).json()
    tasks = await _tasks(session_factory, vi["change_id"])
    kids = [t for t in tasks.values() if t.parent_id == out["recovery"]["summary_task_id"]]
    last = max(t.start_date + timedelta(days=t.duration_days) for t in kids)
    assert out["recovery"]["finish"] == (last - timedelta(days=1)).isoformat()
    assert out["recovery"]["start"] == min(t.start_date for t in kids).isoformat()
