"""Validation issues: the failure branch of stage 9 (spec §12, §12a).

Raise, contain, root cause, the 4-eyes route decision and what each route
does (loop back + recovery group in the plan, concession with a customer
mail, follow-up change), the customer decision, cost and its redaction, fix
actions, re-validation and close, and the escalation levels with their
triggers, history, notifications and acknowledgement.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.utils.clock import business_today
from app.auth.security import get_password_hash
from app.models.change import (
    ChangeAssessment, ChangeAttachment, ChangeChangelog, ChangeRequest,
)
from app.models.change_cost import CostingPosition
from app.models.change_impl import ImplementationEscalation
from app.models.change_plan import ChangePlanDeviation, ChangePlanLink, ChangePlanTask
from app.models.change_validation import ValidationCheck
from app.models.change_validation_issue import (
    ValidationIssue, ValidationIssueAction, ValidationIssueEscalation,
)
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from app.services.validation_issue_service import (
    ValidationIssueService, add_workdays, workdays_between,
)
from tests.conftest import ENGINEER_PASSWORD, login

pytestmark = pytest.mark.asyncio

TODAY = business_today()
D0 = TODAY - timedelta(days=20)          # plan start: validation ended 3 days ago


async def _make(session_factory, seed, *, baseline=False, management=False,
                release_due=None):
    async with session_factory() as s:
        depts = {}
        names = ["Tool Engineer", "Development", "Sales", "Project Manager", "Paint"]
        if management:
            names.append("Management")
        for name in names:
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for key, dept in [("tool", "Tool Engineer"), ("dev", "Development"),
                          ("sales", "Sales"), ("pm", "Project Manager"),
                          ("pm2", "Project Manager"), ("paint", "Paint"),
                          ("lead", None), ("boss", "Management" if management else None)]:
            if key == "boss" and not management:
                continue
            email = f"{key}@vi.test"
            u = User(organization_id=seed["org_id"], username=key, email=email,
                     full_name=key.upper(), role="engineer",
                     hashed_password=get_password_hash(ENGINEER_PASSWORD),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            if dept:
                s.add(UserDepartment(user_id=u.id, department_id=depts[dept]))
            users[key] = {"id": u.id, "email": email}
        change = ChangeRequest(
            change_number="C-VI-1", title="Bracket change", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=users["lead"]["id"],
            status="in_validation", customer_relevant=True,
            impact_confirmed_at=datetime.utcnow(),
            impact_confirmed_by=seed["admin_id"],
            release_due_date=(datetime.combine(release_due, datetime.min.time())
                              if release_due else
                              datetime.combine(TODAY + timedelta(days=120),
                                               datetime.min.time())),
            timing_validated_at=datetime.utcnow() if baseline else None)
        s.add(change)
        await s.flush()
        for name in ("Tool Engineer", "Development"):
            s.add(ChangeAssessment(change_id=change.id, department_id=depts[name],
                                   stage_order=1, verdict="feasible"))
        s.add(CostingPosition(
            change_id=change.id, department_id=depts["Tool Engineer"],
            label="Tool rework", kind="external", pricing="estimate",
            est_cost=1000.0, created_by=seed["admin_id"]))
        failed = ValidationCheck(change_id=change.id, department_id=depts["Tool Engineer"],
                                 check_key="sampled", status="failed",
                                 note="tool does not close", checked_by=users["tool"]["id"],
                                 checked_at=datetime.utcnow())
        passed = ValidationCheck(change_id=change.id, department_id=depts["Tool Engineer"],
                                 check_key="measured", status="passed",
                                 checked_by=users["tool"]["id"], checked_at=datetime.utcnow())
        s.add_all([failed, passed])
        # a status changelog row: the change has been in validation
        s.add(ChangeChangelog(change_id=change.id, action="status_changed",
                              action_description="in_implementation -> in_validation",
                              field_name="status", old_value='"in_implementation"',
                              new_value='"in_validation"', performed_by=seed["admin_id"],
                              performed_at=datetime.utcnow(), entry_hash="x"))
        tasks = {}
        spec = [("A", "work", D0, 10, "Tool Engineer"),
                ("V", "validation", D0 + timedelta(days=10), 7, "Tool Engineer"),
                ("C", "customer", D0 + timedelta(days=17), 14, None),
                ("S", "milestone", D0 + timedelta(days=31), 0, None)]
        for n, (key, kind, start, dur, dept) in enumerate(spec, 1):
            t = ChangePlanTask(change_id=change.id, plan="detailed", name=key, kind=kind,
                               lane=dept or "Customer",
                               department_id=depts.get(dept) if dept else None,
                               start_date=start, duration_days=dur, predecessors=[],
                               sort_order=n, created_by=seed["admin_id"])
            s.add(t)
            await s.flush()
            if baseline:
                t.baseline_start = start
                t.baseline_finish = start + timedelta(days=dur)
            tasks[key] = t.id
        for a, b in (("A", "V"), ("V", "C"), ("C", "S")):
            s.add(ChangePlanLink(change_id=change.id, plan="detailed",
                                 from_task_id=tasks[a], to_task_id=tasks[b],
                                 type="FS", lag_days=0, created_by=seed["admin_id"]))
        await s.commit()
        return {"change_id": change.id, "dept": depts, "user": users,
                "check_id": failed.id, "passed_check_id": passed.id, "tasks": tasks,
                "admin_id": seed["admin_id"]}


@pytest.fixture
async def vi(session_factory, seed):
    return await _make(session_factory, seed)


@pytest.fixture
async def vib(session_factory, seed):
    return await _make(session_factory, seed, baseline=True)


async def _auth(client, vi, key):
    if key == "admin":
        return await login(client, "admin@test.io")
    return await login(client, vi["user"][key]["email"], ENGINEER_PASSWORD)


def _url(vi, suffix=""):
    return f"/api/v1/changes/{vi['change_id']}/validation/issues{suffix}"


async def _raise(client, auth, vi, **kw):
    body = {"title": "Tool does not close", "description": "Slider jams",
            "check_id": vi["check_id"], **kw}
    return await client.post(_url(vi), headers=auth, json=body)


async def _raised(client, vi, who="tool", **kw):
    res = await _raise(client, await _auth(client, vi, who), vi, **kw)
    assert res.status_code == 201, res.text
    return res.json()


async def _ready(client, vi, iid, *, contain=True):
    tool = await _auth(client, vi, "tool")
    if contain:
        r = await client.post(_url(vi, f"/{iid}/contain"), headers=tool,
                              json={"containment": "Parts on hold"})
        assert r.status_code == 200, r.text
    r = await client.post(_url(vi, f"/{iid}/root-cause"), headers=tool,
                          json={"root_cause": "Worn slider"})
    assert r.status_code == 200, r.text


async def _route(client, vi, iid, who="pm", **kw):
    body = {"route": "internal_rework", "reason": "Rework slider",
            "actions": [{"description": "Rework the slider"}], **kw}
    return await client.post(_url(vi, f"/{iid}/route"),
                             headers=await _auth(client, vi, who), json=body)


async def _changelog(session_factory, change_id):
    async with session_factory() as s:
        return list((await s.execute(
            select(ChangeChangelog).where(ChangeChangelog.change_id == change_id)
            .order_by(ChangeChangelog.id))).scalars().all())


async def _svc(session_factory, vi, fn, *args, user="admin_id", commit=True, **kw):
    """Call a service function with a fresh session as `user`."""
    async with session_factory() as s:
        change = await s.get(ChangeRequest, vi["change_id"])
        uid = vi["admin_id"] if user == "admin_id" else vi["user"][user]["id"]
        u = await s.get(User, uid)
        out = await fn(s, change, *args, u, **kw) if u is not None else None
        if commit:
            await s.commit()
        return out


async def _tasks(session_factory, change_id):
    async with session_factory() as s:
        return {t.id: t for t in (await s.execute(
            select(ChangePlanTask).where(ChangePlanTask.change_id == change_id)
        )).scalars().all()}


# --- working-day helpers ----------------------------------------------------

async def test_workday_helpers():
    fri = date(2026, 9, 25)
    assert add_workdays(fri, 1) == date(2026, 9, 28)
    assert add_workdays(fri, 2) == date(2026, 9, 29)
    assert workdays_between(fri, date(2026, 9, 29)) == 2
    assert workdays_between(date(2026, 9, 29), fri) == -2
    assert workdays_between(fri, fri) == 0


# --- raise ------------------------------------------------------------------

async def test_raise_rights_and_prefill_from_failed_check(client, vi):
    paint = await _auth(client, vi, "paint")
    assert (await _raise(client, paint, vi)).status_code == 403
    tool = await _auth(client, vi, "tool")
    pre = await client.get(_url(vi, f"/prefill?check_id={vi['check_id']}"), headers=tool)
    assert pre.status_code == 200, pre.text
    p = pre.json()
    assert p["category"] == "tool" and p["department_id"] == vi["dept"]["Tool Engineer"]
    assert p["can_raise"] is True and p["existing_issue_id"] is None
    issue = await _raised(client, vi)
    assert issue["ref"] == "VI-1" and issue["category"] == "tool"
    assert issue["department_id"] == vi["dept"]["Tool Engineer"]
    assert issue["status"] == "open" and issue["step"] == "raised"
    assert issue["escalation"]["level"] == 1
    assert issue["escalation"]["history"][0]["trigger"] == "raised"
    # one open issue per failed check
    res = await _raise(client, tool, vi)
    assert res.status_code == 400 and "already open" in res.json()["detail"]
    pre = (await client.get(_url(vi, f"/prefill?check_id={vi['check_id']}"),
                            headers=tool)).json()
    assert pre["existing_issue_id"] == issue["id"] and pre["can_raise"] is False
    # a passed check is no source
    res = await _raise(client, tool, vi, check_id=vi["passed_check_id"])
    assert res.status_code == 400
    # without a check: category and severity free, PM may raise
    pm = await _auth(client, vi, "pm")
    res = await _raise(client, pm, vi, check_id=None, category="cosmetic", severity=1,
                       department_id=vi["dept"]["Development"])
    assert res.status_code == 201, res.text
    assert res.json()["number"] == 2 and res.json()["category"] == "cosmetic"
    res = await _raise(client, pm, vi, check_id=None, category="nonsense")
    assert res.status_code == 400


async def test_raise_window(client, vi, session_factory):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, vi["change_id"])
        c.status = "approved"
        await s.commit()
    res = await _raise(client, await _auth(client, vi, "pm"), vi)
    assert res.status_code == 400
    async with session_factory() as s:
        c = await s.get(ChangeRequest, vi["change_id"])
        c.status = "in_implementation"         # after a loop back: allowed
        await s.commit()
    res = await _raise(client, await _auth(client, vi, "pm"), vi)
    assert res.status_code == 201, res.text


async def test_raise_logs_and_notifies_level_1(client, vi, session_factory):
    issue = await _raised(client, vi, who="dev", check_id=None, category="other",
                          department_id=vi["dept"]["Tool Engineer"])
    actions = [e.action for e in await _changelog(session_factory, vi["change_id"])]
    assert "validation_issue_raised" in actions
    assert "validation_issue_escalated" in actions
    async with session_factory() as s:
        notified = set((await s.execute(select(Notification.user_id).where(
            Notification.kind == "validation_issue_escalated"))).scalars().all())
    # owner department + PM informed (not the raiser's own department)
    assert vi["user"]["tool"]["id"] in notified
    assert vi["user"]["pm"]["id"] in notified
    assert vi["user"]["sales"]["id"] not in notified
    assert issue["escalation"]["history"][0]["notified"].startswith("owner department")


# --- containment / root cause -------------------------------------------------

async def test_contain_and_root_cause_rights(client, vi):
    issue = await _raised(client, vi)
    dev = await _auth(client, vi, "dev")
    r = await client.post(_url(vi, f"/{issue['id']}/contain"), headers=dev,
                          json={"containment": "hold"})
    assert r.status_code == 403
    tool = await _auth(client, vi, "tool")
    r = await client.post(_url(vi, f"/{issue['id']}/contain"), headers=tool,
                          json={"containment": ""})
    assert r.status_code == 400
    r = await client.post(_url(vi, f"/{issue['id']}/contain"), headers=tool,
                          json={"containment": "Parts on hold, old tool runs"})
    assert r.status_code == 200 and r.json()["status"] == "contained"
    r = await client.post(_url(vi, f"/{issue['id']}/root-cause"), headers=dev,
                          json={"root_cause": "x"})
    assert r.status_code == 403
    lead = await _auth(client, vi, "lead")
    r = await client.post(_url(vi, f"/{issue['id']}/root-cause"), headers=lead,
                          json={"root_cause": "Worn slider"})
    assert r.status_code == 200 and r.json()["step"] == "root_cause"
    r = await client.patch(_url(vi, f"/{issue['id']}"), headers=dev,
                           json={"title": "x"})
    assert r.status_code == 403
    r = await client.patch(_url(vi, f"/{issue['id']}"), headers=tool,
                           json={"title": "Slider jams at 40 strokes", "severity": 2})
    assert r.status_code == 200 and r.json()["title"] == "Slider jams at 40 strokes"


# --- route --------------------------------------------------------------------

async def test_route_rights_four_eyes_and_preconditions(client, vi):
    issue = await _raised(client, vi, who="pm", severity=3)
    iid = issue["id"]
    # severity 3 raised: level 2 at once
    assert issue["escalation"]["level"] == 2
    assert (await _route(client, vi, iid, who="tool")).status_code == 403
    assert (await _route(client, vi, iid, who="sales")).status_code == 403
    # four eyes: the raiser (PM) may not decide it alone
    r = await _route(client, vi, iid, who="pm")
    assert r.status_code == 403 and "Four eyes" in r.json()["detail"]
    # severity 3 needs containment first
    r = await _route(client, vi, iid, who="pm2")
    assert r.status_code == 400 and "containment" in r.json()["detail"]
    tool = await _auth(client, vi, "tool")
    await client.post(_url(vi, f"/{iid}/contain"), headers=tool,
                      json={"containment": "hold"})
    r = await _route(client, vi, iid, who="pm2")
    assert r.status_code == 400 and "root cause" in r.json()["detail"]
    await client.post(_url(vi, f"/{iid}/root-cause"), headers=tool,
                      json={"root_cause": "worn"})
    r = await _route(client, vi, iid, who="pm2", actions=[])
    assert r.status_code == 400 and "fix action" in r.json()["detail"]
    r = await _route(client, vi, iid, who="pm2", route="bogus")
    assert r.status_code == 400
    r = await _route(client, vi, iid, who="pm2", reason=" ")
    assert r.status_code == 400
    r = await _route(client, vi, iid, who="pm2")
    assert r.status_code == 200, r.text
    assert r.json()["route"] == "internal_rework" and r.json()["status"] == "fixing"
    assert (await _route(client, vi, iid, who="pm2")).status_code == 400


async def test_admin_may_route_own_issue(client, vi):
    issue = await _raised(client, vi, who="admin")
    await _ready(client, vi, issue["id"])
    r = await _route(client, vi, issue["id"], who="admin")
    assert r.status_code == 200, r.text


async def test_fix_route_loops_back_and_builds_recovery_before_baseline(
        client, vi, session_factory):
    issue = await _raised(client, vi)
    await _ready(client, vi, issue["id"])
    due = TODAY + timedelta(days=9)
    r = await _route(client, vi, issue["id"], who="lead", actions=[
        {"description": "Rework the slider", "due_date": due.isoformat()},
        {"description": "Replace the spring"}])
    assert r.status_code == 200, r.text
    out = r.json()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, vi["change_id"])
        assert change.status == "in_implementation"
        assert change.plan_revision >= 1       # before the baseline: an edit
        devs = (await s.execute(select(func.count()).select_from(
            ChangePlanDeviation))).scalar()
        assert devs == 0
    log = await _changelog(session_factory, vi["change_id"])
    esc = [e for e in log if e.action == "validation_escalated"]
    assert esc and esc[0].notes == "VI-1: Tool does not close: Rework slider"
    assert "validation_issue_route_decided" in [e.action for e in log]

    tasks = await _tasks(session_factory, vi["change_id"])
    rec = out["recovery"]
    summary = tasks[rec["task_id"]]
    assert summary.name == "Recovery VI-1: Tool does not close"
    assert summary.lane == "Tool Engineer"
    kids = [t for t in tasks.values() if t.parent_id == summary.id]
    assert {t.kind for t in kids} == {"work", "validation"}
    rv = tasks[rec["revalidation_task_id"]]
    assert rv.name == "Re-validation VI-1" and rv.duration_days == 3
    fixes = sorted([t for t in kids if t.kind == "work"], key=lambda t: t.id)
    assert fixes[0].start_date == business_today()      # never in the past
    assert fixes[0].end_date == due + timedelta(days=1)  # until the due date
    assert fixes[1].duration_days == 7                  # 5 wd in calendar days
    assert rv.start_date == max(f.end_date for f in fixes)
    # the recovery drives what depended on the failed validation
    c = tasks[vi["tasks"]["C"]]
    assert c.start_date == rv.end_date
    assert tasks[vi["tasks"]["S"]].start_date == c.end_date
    async with session_factory() as s:
        pairs = {(lk.from_task_id, lk.to_task_id) for lk in (await s.execute(
            select(ChangePlanLink))).scalars().all()}
    assert (vi["tasks"]["V"], summary.id) in pairs
    assert (rv.id, vi["tasks"]["C"]) in pairs
    assert all((f.id, rv.id) in pairs for f in fixes)
    assert {a["plan_task_id"] for a in out["actions"]} == {f.id for f in fixes}
    assert rec["finish"] == (rv.end_date - timedelta(days=1)).isoformat()
    assert rec["baseline_finish"] is None and rec["slip_days"] is None


async def test_recovery_after_baseline_is_deviations(client, vib, session_factory):
    vi = vib
    issue = await _raised(client, vi)
    await _ready(client, vi, issue["id"])
    r = await _route(client, vi, issue["id"], who="lead")
    assert r.status_code == 200, r.text
    out = r.json()
    rec = out["recovery"]
    tasks = await _tasks(session_factory, vi["change_id"])
    async with session_factory() as s:
        devs = list((await s.execute(select(ChangePlanDeviation))).scalars().all())
        change = await s.get(ChangeRequest, vi["change_id"])
        assert change.plan_revision == 0       # after the baseline: no bump
    assert devs and all(d.reason == "VI-1: Rework slider" for d in devs)
    moved = {d.task_id: d for d in devs if d.caused_by_task_id == rec["task_id"]}
    assert set(moved) == {vi["tasks"]["C"], vi["tasks"]["S"]}
    c = tasks[vi["tasks"]["C"]]
    assert moved[c.id].new_start == c.start_date
    assert moved[c.id].slip_days == (c.end_date - c.baseline_finish).days > 0
    assert any(d.task_id == rec["task_id"] for d in devs)
    assert rec["slip_days"] > 0 and rec["slip_workdays"] > 0
    assert rec["plan_finish"] > rec["baseline_finish"]
    # the slip past the baseline is a level-2 trigger
    assert out["escalation"]["level"] == 2
    assert "plan_slip" in [h["trigger"] for h in out["escalation"]["history"]]
    assert "plan_deviation" in [e.action for e in await _changelog(
        session_factory, vi["change_id"])]


async def test_route_without_plan_skips_recovery(client, vi, session_factory):
    async with session_factory() as s:
        for lk in (await s.execute(select(ChangePlanLink))).scalars().all():
            await s.delete(lk)
        await s.flush()
        for t in (await s.execute(select(ChangePlanTask))).scalars().all():
            await s.delete(t)
        await s.commit()
    issue = await _raised(client, vi)
    await _ready(client, vi, issue["id"])
    r = await _route(client, vi, issue["id"], who="lead")
    assert r.status_code == 200, r.text
    assert r.json()["recovery"] is None


async def test_design_change_informs_customer_and_supplier_rework_needs_supplier(
        client, vi):
    a = await _raised(client, vi)
    await _ready(client, vi, a["id"])
    r = await _route(client, vi, a["id"], who="lead", route="supplier_rework")
    assert r.status_code == 400 and "supplier" in r.json()["detail"]
    r = await _route(client, vi, a["id"], who="lead", route="supplier_rework",
                     supplier_name="Hasco", chargeback=True)
    assert r.status_code == 200, r.text
    assert r.json()["supplier_name"] == "Hasco" and r.json()["chargeback"] is True
    assert r.json()["customer_inform"] is False
    b = await _raised(client, vi, check_id=None, category="dimensional",
                      department_id=vi["dept"]["Tool Engineer"])
    await _ready(client, vi, b["id"])
    r = await _route(client, vi, b["id"], who="lead", route="design_change")
    assert r.status_code == 200, r.text
    assert r.json()["customer_inform"] is True


async def test_follow_up_change_transfers_the_issue(client, vi, session_factory):
    issue = await _raised(client, vi)
    await _ready(client, vi, issue["id"])
    r = await _route(client, vi, issue["id"], who="lead", route="follow_up_change",
                     actions=[])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "transferred" and out["is_open"] is False
    async with session_factory() as s:
        follow = await s.get(ChangeRequest, out["follow_up_change_id"])
        change = await s.get(ChangeRequest, vi["change_id"])
        assert follow.status == "captured"
        assert follow.project_id == change.project_id
        assert follow.reason == "Follow-up of C-VI-1 VI-1"
        assert follow.lead_id == change.lead_id
        assert "Slider jams" in follow.description
        assert change.status == "in_validation"      # no loop back
        assert await ValidationIssueService.release_blocker(s, change) is None
    assert out["follow_up_change_number"] == follow.change_number
    assert "validation_issue_transferred" in [
        e.action for e in await _changelog(session_factory, vi["change_id"])]


# --- customer -------------------------------------------------------------------

async def _mail(session_factory, vi, iid, kind="customer_email"):
    async with session_factory() as s:
        s.add(ChangeAttachment(change_id=vi["change_id"], filename="mail.eml",
                               stored_path="x", content_type="message/rfc822",
                               size_bytes=10, sha256="0" * 64, kind=kind,
                               phase="post_scoping", validation_issue_id=iid,
                               uploaded_by=vi["user"]["sales"]["id"]))
        await s.commit()


async def test_concession_needs_sales_and_a_customer_mail(client, vi, session_factory):
    issue = await _raised(client, vi, check_id=None, category="cosmetic")
    iid = issue["id"]
    # concession may be decided with the cause still open, informs the customer
    r = await _route(client, vi, iid, who="pm", route="customer_concession",
                     actions=[], customer_inform=False)
    assert r.status_code == 400
    r = await _route(client, vi, iid, who="pm", route="customer_concession", actions=[])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "route_decided" and r.json()["customer_inform"]
    sales = await _auth(client, vi, "sales")
    view = (await client.get(_url(vi, f"/{iid}"), headers=sales)).json()
    assert view["primary_act"] == "customer"
    body = {"decision": "accept_deviation", "note": "Customer accepts as is"}
    pm = await _auth(client, vi, "pm")
    assert (await client.post(_url(vi, f"/{iid}/customer"), headers=pm,
                              json=body)).status_code == 403
    r = await client.post(_url(vi, f"/{iid}/customer"), headers=sales, json=body)
    assert r.status_code == 400 and "mail" in r.json()["detail"]
    await _mail(session_factory, vi, iid, kind="general")
    r = await client.post(_url(vi, f"/{iid}/customer"), headers=sales, json=body)
    assert r.status_code == 400
    await _mail(session_factory, vi, iid)
    r = await client.post(_url(vi, f"/{iid}/customer"), headers=sales,
                          json={**body, "concession_until": "2027-03-31"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "accepted" and out["has_customer_mail"]
    assert out["concession_until"] == "2027-03-31"
    assert len(out["attachments"]) == 2


async def test_require_fix_on_concession_reopens_route_and_goes_level_3(
        client, vi):
    issue = await _raised(client, vi, check_id=None, category="cosmetic",
                          department_id=vi["dept"]["Tool Engineer"])
    iid = issue["id"]
    await _route(client, vi, iid, who="pm", route="customer_concession", actions=[])
    sales = await _auth(client, vi, "sales")
    r = await client.post(_url(vi, f"/{iid}/customer"), headers=sales,
                          json={"decision": "require_fix", "note": "Fix it"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["route"] is None and out["status"] == "open"
    assert out["escalation"]["level"] == 3
    assert out["escalation"]["latest"]["trigger"] == "require_fix"
    # the route can be decided again (now a fix)
    await _ready(client, vi, iid, contain=False)
    r = await _route(client, vi, iid, who="pm")
    assert r.status_code == 200, r.text
    assert r.json()["customer_decision"] is None


async def test_new_timing_moves_release_deadline_and_escalates_recovery(
        client, session_factory, seed):
    vi = await _make(session_factory, seed, baseline=True,
                     release_due=TODAY + timedelta(days=5))
    issue = await _raised(client, vi)
    await _ready(client, vi, issue["id"])
    r = await _route(client, vi, issue["id"], who="lead")
    out = r.json()
    # recovery ends after the release deadline: level 3, customer informed
    assert out["escalation"]["level"] == 3
    assert out["escalation"]["latest"]["trigger"] == "release_deadline"
    assert out["customer_inform"] is True
    assert out["recovery"]["past_deadline_days"] > 0
    assert out["recovery"]["needs_timing_decision"] is True
    sales = await _auth(client, vi, "sales")
    r = await client.post(_url(vi, f"/{issue['id']}/customer"), headers=sales,
                          json={"decision": "new_timing", "note": "New SOP agreed"})
    assert r.status_code == 400
    new = TODAY + timedelta(days=90)
    r = await client.post(_url(vi, f"/{issue['id']}/customer"), headers=sales,
                          json={"decision": "new_timing", "note": "New SOP agreed",
                                "new_date": new.isoformat()})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["new_timing_date"] == new.isoformat()
    assert out["recovery"]["needs_timing_decision"] is False
    async with session_factory() as s:
        change = await s.get(ChangeRequest, vi["change_id"])
        assert change.release_due_date.date() == new
        assert change.release_due_date.time().isoformat() == "23:59:59"
        assert change.release_due_reason == "VI-1: New SOP agreed"
        devs = list((await s.execute(select(ChangePlanDeviation))).scalars().all())
        escs = list((await s.execute(select(ImplementationEscalation))).scalars().all())
    assert len(escs) == 1 and escs[0].direction == "customer"
    assert devs and all(d.status == "escalated" and d.escalation_id == escs[0].id
                        for d in devs)
    assert out["customer_escalation_id"] == escs[0].id
    assert "release_deadline_set" in [e.action for e in await _changelog(
        session_factory, vi["change_id"])]


# --- cost ---------------------------------------------------------------------

async def test_cost_rights_redaction_and_quote_task(client, vi, session_factory):
    issue = await _raised(client, vi)
    iid = issue["id"]
    tool = await _auth(client, vi, "tool")
    r = await client.post(_url(vi, f"/{iid}/cost"), headers=tool,
                          json={"extra_cost": 5000, "cost_bearer": "customer"})
    assert r.status_code == 403
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{iid}/cost"), headers=pm,
                          json={"extra_cost": 5000})
    assert r.status_code == 400
    r = await client.post(_url(vi, f"/{iid}/cost"), headers=pm,
                          json={"extra_cost": 5000, "cost_bearer": "nobody"})
    assert r.status_code == 400
    r = await client.post(_url(vi, f"/{iid}/cost"), headers=pm,
                          json={"extra_cost": 5000, "cost_bearer": "customer"})
    assert r.status_code == 200 and r.json()["extra_cost"] == 5000
    seen = (await client.get(_url(vi), headers=tool)).json()[0]
    assert seen["extra_cost"] is None and seen["cost_visible"] is False
    assert seen["cost_set"] is True
    assert seen["cost_bearer"] == "customer"
    sales = await _auth(client, vi, "sales")
    seen = (await client.get(_url(vi), headers=sales)).json()[0]
    assert seen["extra_cost"] == 5000 and "quote_fix" in seen["extra_acts"]
    assert seen["cost_set"] is True and "cost" not in seen["next_acts"]
    mine = await _svc(session_factory, vi, ValidationIssueService.my_actions,
                      user="sales", commit=False)
    assert "validation_issue_quote" in [a["kind"] for a in mine]
    assert (await client.post(_url(vi, f"/{iid}/fix-quoted"), headers=pm,
                              json={})).status_code == 403
    r = await client.post(_url(vi, f"/{iid}/fix-quoted"), headers=sales, json={})
    assert r.status_code == 200 and r.json()["fix_quoted_at"]
    assert "quote_fix" not in r.json()["extra_acts"]


# --- actions, re-validation, close --------------------------------------------

async def test_actions_revalidation_and_check_closes(client, vi, session_factory):
    issue = await _raised(client, vi)
    iid = issue["id"]
    await _ready(client, vi, iid)
    r = await _route(client, vi, iid, who="lead", actions=[
        {"description": "Rework", "department_id": vi["dept"]["Tool Engineer"]}])
    aid = r.json()["actions"][0]["id"]
    dev = await _auth(client, vi, "dev")
    r = await client.post(_url(vi, f"/{iid}/actions/{aid}/done"), headers=dev)
    assert r.status_code == 403
    tool = await _auth(client, vi, "tool")
    r = await client.post(_url(vi, f"/{iid}/actions"), headers=tool,
                          json={"description": "Check the spring",
                                "owner_id": vi["user"]["dev"]["id"]})
    assert r.status_code == 201, r.text
    aid2 = [a for a in r.json()["actions"] if a["id"] != aid][0]["id"]
    r = await client.post(_url(vi, f"/{iid}/actions/{aid}/done"), headers=tool)
    assert r.status_code == 200 and r.json()["status"] == "fixing"
    assert (await client.post(_url(vi, f"/{iid}/actions/{aid}/done"),
                              headers=tool)).status_code == 400
    # the owner of an action may mark it done
    r = await client.post(_url(vi, f"/{iid}/actions/{aid2}/done"), headers=dev)
    assert r.status_code == 200 and r.json()["status"] == "revalidation"
    # linked to a check: no manual close
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{iid}/close"), headers=pm, json={"note": "ok"})
    assert r.status_code == 400 and "passed" in r.json()["detail"]
    # a new failed answer: back to fixing
    async with session_factory() as s:
        chk = await s.get(ValidationCheck, vi["check_id"])
        change = await s.get(ChangeRequest, vi["change_id"])
        u = await s.get(User, vi["user"]["tool"]["id"])
        res = await ValidationIssueService.on_check_answered(s, change, chk, u)
        await s.commit()
    assert res == {"closed": [], "reopened": [iid], "revalidated_early": [],
                   "offer_raise": False}
    assert (await client.get(_url(vi, f"/{iid}"), headers=pm)).json()["status"] == "fixing"
    async with session_factory() as s:
        chk = await s.get(ValidationCheck, vi["check_id"])
        chk.status = "passed"
        change = await s.get(ChangeRequest, vi["change_id"])
        u = await s.get(User, vi["user"]["tool"]["id"])
        res = await ValidationIssueService.on_check_answered(s, change, chk, u)
        await s.commit()
    assert res["closed"] == [iid]
    out = (await client.get(_url(vi, f"/{iid}"), headers=pm)).json()
    assert out["status"] == "closed" and out["next_acts"] == []
    actions = [e.action for e in await _changelog(session_factory, vi["change_id"])]
    for a in ("validation_issue_action_done", "validation_issue_revalidated",
              "validation_issue_closed"):
        assert a in actions


async def test_failed_check_without_issue_offers_raise(client, vi, session_factory):
    async with session_factory() as s:
        chk = await s.get(ValidationCheck, vi["check_id"])
        change = await s.get(ChangeRequest, vi["change_id"])
        u = await s.get(User, vi["user"]["tool"]["id"])
        res = await ValidationIssueService.on_check_answered(s, change, chk, u)
    assert res["offer_raise"] is True


async def test_close_without_check_by_pm(client, vi):
    issue = await _raised(client, vi, check_id=None, category="other",
                          department_id=vi["dept"]["Tool Engineer"])
    iid = issue["id"]
    await _ready(client, vi, iid)
    r = await _route(client, vi, iid, who="pm")
    aid = r.json()["actions"][0]["id"]
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{iid}/close"), headers=pm, json={"note": "ok"})
    assert r.status_code == 400                           # still fixing
    await client.post(_url(vi, f"/{iid}/actions/{aid}/done"), headers=pm)
    tool = await _auth(client, vi, "tool")
    assert (await client.post(_url(vi, f"/{iid}/close"), headers=tool,
                              json={"note": "ok"})).status_code == 403
    assert (await client.post(_url(vi, f"/{iid}/close"), headers=pm,
                              json={"note": ""})).status_code == 400
    view = (await client.get(_url(vi, f"/{iid}"), headers=pm)).json()
    assert view["primary_act"] == "close"
    r = await client.post(_url(vi, f"/{iid}/close"), headers=pm,
                          json={"note": "Re-measured, fine"})
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert (await client.post(_url(vi, f"/{iid}/contain"), headers=pm,
                              json={"containment": "x"})).status_code == 400


async def test_release_blocker_counts_open_issues(client, vi, session_factory):
    await _raised(client, vi)
    await _raised(client, vi, check_id=None, category="other")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, vi["change_id"])
        assert await ValidationIssueService.release_blocker(s, change) == \
            "2 validation issues open"
    summ = (await client.get(_url(vi, "/summary"),
                             headers=await _auth(client, vi, "pm"))).json()
    assert summ["open_count"] == 2 and summ["highest_level"] == 1


# --- escalation ---------------------------------------------------------------

async def _backdate_issue(session_factory, iid, days):
    async with session_factory() as s:
        i = await s.get(ValidationIssue, iid)
        i.created_at = datetime.utcnow() - timedelta(days=days)
        await s.commit()


async def test_no_route_after_two_working_days_goes_level_2(client, vi, session_factory):
    issue = await _raised(client, vi)
    async with session_factory() as s:
        assert await ValidationIssueService.reevaluate_all(s) == 0
    await _backdate_issue(session_factory, issue["id"], 7)
    async with session_factory() as s:
        assert await ValidationIssueService.reevaluate_all(s) == 1
        await s.commit()
    async with session_factory() as s:
        # the same trigger does not fire twice
        assert await ValidationIssueService.reevaluate_all(s) == 0
        i = await s.get(ValidationIssue, issue["id"])
        assert i.escalation_level == 2
        rows = list((await s.execute(select(ValidationIssueEscalation).where(
            ValidationIssueEscalation.issue_id == i.id))).scalars().all())
        assert rows[-1].trigger == "no_route" and rows[-1].created_by is None
        notified = set((await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"vi:{i.id}:esc:{rows[-1].id}"))).scalars().all())
    assert {vi["user"]["pm"]["id"], vi["user"]["lead"]["id"],
            vi["user"]["sales"]["id"]} <= notified


async def test_overdue_action_goes_level_2(client, vi, session_factory):
    issue = await _raised(client, vi)
    await _ready(client, vi, issue["id"])
    r = await _route(client, vi, issue["id"], who="lead", actions=[
        {"description": "Rework"}])
    assert r.json()["escalation"]["level"] == 1
    async with session_factory() as s:
        a = (await s.execute(select(ValidationIssueAction))).scalars().first()
        a.due_date = TODAY - timedelta(days=1)
        await s.commit()
    async with session_factory() as s:
        assert await ValidationIssueService.reevaluate_all(s) == 1
        await s.commit()
    out = (await client.get(_url(vi, f"/{issue['id']}"),
                            headers=await _auth(client, vi, "pm"))).json()
    assert out["escalation"]["latest"]["trigger"] == "action_overdue"
    assert out["actions"][0]["overdue"] is True


async def test_unacknowledged_level_2_goes_level_3_and_ack_stops_it(
        client, session_factory, seed):
    vi = await _make(session_factory, seed, management=True)
    a = await _raised(client, vi, severity=3)
    b = await _raised(client, vi, check_id=None, severity=3, category="other")
    assert a["escalation"]["level"] == 2 and a["escalation"]["unacknowledged"]
    sales = await _auth(client, vi, "sales")
    tool = await _auth(client, vi, "tool")
    esc_b = b["escalation"]["latest"]
    # the tool shop was not notified at level 2
    r = await client.post(_url(vi, f"/{b['id']}/escalations/{esc_b['id']}/acknowledge"),
                          headers=tool)
    assert r.status_code == 403
    view = (await client.get(_url(vi, f"/{b['id']}"), headers=sales)).json()
    assert "acknowledge" in view["next_acts"] and view["primary_act"] == "acknowledge"
    mine = await _svc(session_factory, vi, ValidationIssueService.my_actions,
                      user="sales", commit=False)
    assert "Acknowledge escalation VI-2 (level 2)" in [m["label"] for m in mine]
    r = await client.post(_url(vi, f"/{b['id']}/escalations/{esc_b['id']}/acknowledge"),
                          headers=sales)
    assert r.status_code == 200, r.text
    assert r.json()["escalation"]["unacknowledged"] is False
    assert r.json()["escalation"]["latest"]["acknowledged_by_name"] == "SALES"
    assert (await client.post(
        _url(vi, f"/{b['id']}/escalations/{esc_b['id']}/acknowledge"),
        headers=sales)).status_code == 400
    async with session_factory() as s:
        for e in (await s.execute(select(ValidationIssueEscalation))).scalars().all():
            e.created_at = datetime.utcnow() - timedelta(days=7)
        await s.commit()
    async with session_factory() as s:
        assert await ValidationIssueService.reevaluate_all(s) == 1
        await s.commit()
    async with session_factory() as s:
        ia = await s.get(ValidationIssue, a["id"])
        ib = await s.get(ValidationIssue, b["id"])
        assert ia.escalation_level == 3 and ib.escalation_level == 2
        assert ia.customer_inform is True
        last = (await s.execute(select(ValidationIssueEscalation).where(
            ValidationIssueEscalation.issue_id == ia.id)
            .order_by(ValidationIssueEscalation.id.desc()))).scalars().first()
        assert last.trigger == "unacknowledged" and "Management" in last.notified
        boss = set((await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"vi:{ia.id}:esc:{last.id}"))).scalars().all())
    assert vi["user"]["boss"]["id"] in boss


async def test_level_3_without_management_notifies_admins(client, session_factory, seed):
    vi = await _make(session_factory, seed)
    issue = await _raised(client, vi, check_id=None, category="other")
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{issue['id']}/escalate"), headers=pm,
                          json={"reason": "Customer line down", "level": 3})
    assert r.status_code == 200, r.text
    latest = r.json()["escalation"]["latest"]
    assert latest["trigger"] == "manual" and latest["level"] == 3
    assert "admins" in latest["notified"]
    async with session_factory() as s:
        got = set((await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"vi:{issue['id']}:esc:{latest['id']}"
        ))).scalars().all())
    assert vi["admin_id"] in got


async def test_manual_escalation_and_deescalation_rights(client, vi, session_factory):
    issue = await _raised(client, vi, check_id=None, category="other")
    iid = issue["id"]
    tool = await _auth(client, vi, "tool")
    assert (await client.post(_url(vi, f"/{iid}/escalate"), headers=tool,
                              json={"reason": "x"})).status_code == 403
    sales = await _auth(client, vi, "sales")
    assert (await client.post(_url(vi, f"/{iid}/escalate"), headers=sales,
                              json={"reason": ""})).status_code == 400
    r = await client.post(_url(vi, f"/{iid}/escalate"), headers=sales,
                          json={"reason": "Customer asks"})
    assert r.status_code == 200 and r.json()["escalation"]["level"] == 2
    assert (await client.post(_url(vi, f"/{iid}/escalate"), headers=sales,
                              json={"reason": "again", "level": 2})).status_code == 400
    assert (await client.post(_url(vi, f"/{iid}/deescalate"), headers=sales,
                              json={"reason": "ok"})).status_code == 403
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{iid}/deescalate"), headers=pm,
                          json={"reason": "Customer calmed down"})
    assert r.status_code == 200 and r.json()["escalation"]["level"] == 1
    assert r.json()["escalation"]["latest"]["trigger"] == "deescalate"
    # a manual level-2 row still needs no ack after the PM lowered it
    async with session_factory() as s:
        assert await ValidationIssueService.reevaluate_all(s) == 0


async def test_my_actions_kinds(client, vi, session_factory):
    await _raised(client, vi, severity=3, who="dev", check_id=None,
                  category="tool", department_id=vi["dept"]["Tool Engineer"])
    tool = await _svc(session_factory, vi, ValidationIssueService.my_actions,
                      user="tool", commit=False)
    assert {a["kind"] for a in tool} == {"validation_issue_contain",
                                        "validation_issue_root_cause"}
    assert all(a["target_tab"] == "release" for a in tool)
    pm = await _svc(session_factory, vi, ValidationIssueService.my_actions,
                    user="pm", commit=False)
    kinds = [a["kind"] for a in pm]
    assert "validation_issue_escalation" in kinds
    # route needs containment first at severity 3
    assert "validation_issue_route" not in kinds


# --- wiring into the change (phase 2) --------------------------------------------

async def test_release_guard_names_open_issues(client, vi, session_factory):
    issue = await _raised(client, vi, check_id=None, category="other")
    async with session_factory() as s:
        chk = await s.get(ValidationCheck, vi["check_id"])
        chk.status = "passed"
        await s.commit()
    admin = await _auth(client, vi, "admin")
    r = await client.post(f"/api/v1/changes/{vi['change_id']}/transition",
                          headers=admin, json={"to_status": "released"})
    assert r.status_code == 400
    assert "1 validation issue open" in r.json()["detail"]
    rel = (await client.get(f"/api/v1/changes/{vi['change_id']}/release",
                            headers=admin)).json()
    assert "1 validation issue open" in rel["blockers"]
    pm = await _auth(client, vi, "pm")
    await client.post(_url(vi, f"/{issue['id']}/close"), headers=pm,
                      json={"note": "raised in error"})
    rel = (await client.get(f"/api/v1/changes/{vi['change_id']}/release",
                            headers=admin)).json()
    assert not any("validation issue" in b for b in rel["blockers"])


async def test_check_answer_through_the_api_closes_the_linked_issue(client, vi):
    issue = await _raised(client, vi)
    iid = issue["id"]
    await _ready(client, vi, iid)
    r = await _route(client, vi, iid, who="lead")
    aid = r.json()["actions"][0]["id"]
    pm = await _auth(client, vi, "pm")
    await client.post(_url(vi, f"/{iid}/actions/{aid}/done"), headers=pm)
    checks = f"/api/v1/changes/{vi['change_id']}/validation/checks"
    body = {"department_id": vi["dept"]["Tool Engineer"], "check_key": "sampled"}
    r = await client.post(checks, headers=pm, json={**body, "status": "failed"})
    assert r.status_code == 201, r.text
    assert (await client.get(_url(vi, f"/{iid}"), headers=pm)).json()["status"] == "fixing"
    r = await client.post(checks, headers=pm, json={**body, "status": "passed"})
    assert r.status_code == 201, r.text
    out = (await client.get(_url(vi, f"/{iid}"), headers=pm)).json()
    assert out["status"] == "closed"
    assert out["closure_note"] == "Re-validated: the linked check passed"


async def _upload(client, auth, vi, iid, kind="customer_email"):
    return await client.post(
        f"/api/v1/changes/{vi['change_id']}/attachments", headers=auth,
        files={"file": ("mail.eml", b"From: customer", "message/rfc822")},
        data={"kind": kind, "validation_issue_id": str(iid)})


async def test_upload_into_an_issue_with_rights(client, vi):
    issue = await _raised(client, vi, check_id=None, category="cosmetic")
    iid = issue["id"]
    await _route(client, vi, iid, who="pm", route="customer_concession", actions=[])
    paint = await _auth(client, vi, "paint")
    assert (await _upload(client, paint, vi, iid)).status_code == 403
    sales = await _auth(client, vi, "sales")
    assert (await _upload(client, sales, vi, iid, kind="info_request")).status_code == 400
    assert (await _upload(client, sales, vi, 9999)).status_code == 404
    r = await _upload(client, sales, vi, iid)
    assert r.status_code == 201, r.text
    assert r.json()["validation_issue_id"] == iid
    r = await client.post(_url(vi, f"/{iid}/customer"), headers=sales,
                          json={"decision": "accept_deviation", "note": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert r.json()["attachments"][0]["kind"] == "customer_email"
    # the issue is closed: nothing more is filed into it
    assert (await _upload(client, sales, vi, iid)).status_code == 400
    atts = (await client.get(f"/api/v1/changes/{vi['change_id']}",
                             headers=sales)).json().get("attachments") or []
    assert any(a.get("validation_issue_id") == iid for a in atts)


async def test_my_actions_and_my_tasks_carry_issue_rows(client, vi):
    issue = await _raised(client, vi, check_id=None, category="cosmetic",
                          department_id=vi["dept"]["Tool Engineer"])
    await _route(client, vi, issue["id"], who="pm", route="customer_concession",
                 actions=[])
    sales = await _auth(client, vi, "sales")
    acts = (await client.get(f"/api/v1/changes/{vi['change_id']}/my-actions",
                             headers=sales)).json()
    rows = acts if isinstance(acts, list) else acts.get("actions", [])
    assert any(a["kind"] == "validation_issue_customer" for a in rows)
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    mine = [t for t in tasks if t["kind"] == "validation_issue_customer"]
    assert mine and mine[0]["issue_id"] == issue["id"]
    assert mine[0]["target_tab"] == "release" and mine[0]["change_id"] == vi["change_id"]
    await _raised(client, vi, who="pm", check_id=None, category="tool",
                  department_id=vi["dept"]["Tool Engineer"])
    tool = await _auth(client, vi, "tool")
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=tool)).json()
    assert "validation_issue_root_cause" in [t["kind"] for t in tasks]


async def test_changelog_redacts_the_extra_cost(client, vi):
    issue = await _raised(client, vi)
    pm = await _auth(client, vi, "pm")
    await client.post(_url(vi, f"/{issue['id']}/cost"), headers=pm,
                      json={"extra_cost": 1234, "cost_bearer": "internal"})
    tool = await _auth(client, vi, "tool")
    log = (await client.get(f"/api/v1/changes/{vi['change_id']}/changelog",
                            headers=tool)).json()
    row = [e for e in log if e["action"] == "validation_issue_cost"][0]
    assert "1234" not in str(row)
    log = (await client.get(f"/api/v1/changes/{vi['change_id']}/changelog",
                            headers=pm)).json()
    row = [e for e in log if e["action"] == "validation_issue_cost"][0]
    assert "1234" in str(row)


async def test_the_sweep_reevaluates_escalations(client, vi, session_factory):
    from app.services.notification_sweep import run_notification_sweep
    issue = await _raised(client, vi)
    await _backdate_issue(session_factory, issue["id"], 7)
    async with session_factory() as s:
        counts = await run_notification_sweep(s)
        await s.commit()
    assert counts["validation_issue_escalated"] == 1


async def test_issue_on_a_check_no_longer_asked_closes_with_a_note(
        client, vi, session_factory):
    """A failed check its department no longer owes (the cycle time of
    Manufacturing / Process Engineer, Development's 'sampled') can never pass
    again: no new issue is linked to it, and an issue already linked closes
    with a note, whatever step it is at."""
    issue = await _raised(client, vi)
    async with session_factory() as s:
        chk = await s.get(ValidationCheck, vi["check_id"])
        chk.department_id = vi["dept"]["Development"]   # sampled: not Development's
        await s.commit()
    pm = await _auth(client, vi, "pm")
    async with session_factory() as s:
        s.add(ValidationCheck(change_id=vi["change_id"],
                              department_id=vi["dept"]["Development"],
                              check_key="measured", status="failed", note="x"))
        await s.commit()
        other = (await s.execute(select(ValidationCheck.id).where(
            ValidationCheck.change_id == vi["change_id"],
            ValidationCheck.department_id == vi["dept"]["Development"],
            ValidationCheck.check_key == "measured"))).scalar_one()
    res = await _raise(client, pm, vi, check_id=other)
    assert res.status_code == 400 and "no longer asked" in res.json()["detail"]
    r = await client.post(_url(vi, f"/{issue['id']}/close"), headers=pm,
                          json={"note": "No longer asked of the department"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"


async def test_extra_cost_is_in_the_costing_currency(client, vi, session_factory, seed):
    """The extra cost is stated in the change's costing currency (its
    costing plant's), like the actual costs: USD at a USD plant, not EUR."""
    from app.models.entities import Plant, Project
    async with session_factory() as s:
        project = await s.get(Project, seed["project_id"])
        plant = await s.get(Plant, project.plant_id)
        plant.currency = "USD"
        await s.commit()
    issue = await _raised(client, vi)
    pm = await _auth(client, vi, "pm")
    r = await client.post(_url(vi, f"/{issue['id']}/cost"), headers=pm,
                          json={"extra_cost": 5000, "cost_bearer": "internal"})
    assert r.status_code == 200, r.text
    assert r.json()["currency"] == "USD"
    seen = (await client.get(_url(vi), headers=pm)).json()[0]
    assert seen["currency"] == "USD" and seen["extra_cost"] == 5000
