"""ECR-solid lane L7, review loop 2 (RELEASE_V2, spec §10):

- one rule for a department's first measurement and its retest: its own
  members; PM or the lead only when it has no member here; a real admin's
  own department rows never count (HARD #3, "admin cannot lift");
- the concession has one entry point (Quality's Request concession), not
  /route; a follow-up change does not take a failed check off this change;
- an expired concession no longer covers the failed check;
- the light Fix path does not escalate "No route decided" once Quality
  picked who fixes; the FAIL notice reaches Quality, the Fix pick the fix
  and retest departments.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select, update

from app.models.change import ChangeRequest
from app.models.change_validation_issue import (
    ValidationIssue, ValidationIssueEscalation,
)
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from app.utils.clock import business_today
from app.services.validation_issue_service import add_workdays
from tests.test_ecr_solid_fix_concession import (  # noqa: F401
    REF, SPEC, _fail_weight, _issue, _iurl, _kinds, _who, fix,
)
from tests.test_validation_checks import _auth, _confirm_limits, _state, _url, val  # noqa: F401

pytestmark = pytest.mark.asyncio

RETEST = {"what_changed_kind": "parameter",
          "what_changed_ref": "holding pressure -5 bar, PS-114 rev C"}


def _weight(lo, hi, **extra):
    return {"department_id": None, "check_key": "weight",
            "measurement": {"sample_size": 5, "min_value": lo, "max_value": hi,
                            "measuring_ref": REF, **SPEC, **extra}}


async def _post_weight(client, auth, fix, lo, hi, **extra):
    body = _weight(lo, hi, **extra)
    body["department_id"] = fix["dept"]["Tool Engineer"]
    return await client.post(_url(fix, "/checks"), headers=auth, json=body)


async def _pick_fix(client, fix, iid):
    res = await client.post(_iurl(fix, f"/{iid}/fix"),
                            headers=await _who(client, fix, "Quality"), json={
        "owner": "process_parameters",
        "retest_due": add_workdays(business_today(), 3).isoformat()})
    assert res.status_code == 200, res.text
    return res.json()


async def _admin_in(session_factory, *dept_ids):
    async with session_factory() as s:
        admin = (await s.execute(select(User).where(
            User.email == "admin@test.io"))).scalar_one()
        for d in dept_ids:
            s.add(UserDepartment(user_id=admin.id, department_id=d))
        await s.commit()
        return admin.id


# --- one rule for the first measurement and the retest -----------------------

async def test_pm_retests_a_member_less_departments_failed_check(
        client, fix, session_factory):
    """Tool Engineer has no member here: PM measured it first, so PM (and
    the lead) retest it too; the lead gets the Retest task. No dead end."""
    pm_id = fix["user"]["Project Manager"]["id"]
    async with session_factory() as s:
        (await s.get(User, fix["user"]["Tool Engineer"]["id"])).is_active = False
        (await s.get(ChangeRequest, fix["change_id"])).lead_id = pm_id
        await s.commit()
    pm = await _auth(client, fix, "Project Manager")
    res = await _post_weight(client, pm, fix, 509.0, 518.0)
    assert res.status_code == 201 and res.json()["status"] == "failed", res.text
    iid = (await _issue(client, fix))["id"]
    await _pick_fix(client, fix, iid)
    tasks = await _kinds(client, pm, fix["change_id"])
    retest = tasks["validation_issue_recheck"]
    assert retest["label"].startswith("Retest for VI-1 by")
    # A5-04 d: one phrase, the lead by name
    assert "Tool Engineer has no member here: Project Manager coordinates" in retest["label"]
    issue = (await client.get(_iurl(fix, f"/{iid}"), headers=pm)).json()
    assert "recheck" in issue["next_acts"]
    st = await _state(client, pm, fix)
    assert {d["department_name"]: d["can_write"]
            for d in st["departments"]}["Tool Engineer"] is True
    res = await _post_weight(client, pm, fix, 503.0, 509.0, **RETEST)
    assert res.status_code == 201 and res.json()["status"] == "passed", res.text
    await _confirm_limits(client, fix, res.json()["id"])       # A5-02 / D5: APQP
    assert (await client.get(_iurl(fix, f"/{iid}"), headers=pm)).json()["status"] == "closed"


async def test_negative_pm_and_admin_do_not_retest_a_staffed_departments_check(
        client, fix, admin_auth):
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    await _pick_fix(client, fix, iid)
    pm = await _auth(client, fix, "Project Manager")
    for auth in (pm, admin_auth):
        res = await _post_weight(client, auth, fix, 503.0, 509.0, **RETEST)
        assert res.status_code == 403, res.text
        issue = (await client.get(_iurl(fix, f"/{iid}"), headers=auth)).json()
        assert "recheck" not in issue["next_acts"]
    assert "validation_issue_recheck" not in await _kinds(client, pm, fix["change_id"])


async def test_negative_an_admin_retests_no_member_less_department(
        client, fix, admin_auth, session_factory):
    """Even with no member in Tool Engineer, a real admin is no coordinator
    (admin cannot lift HARD #3); the lead here is the admin itself."""
    async with session_factory() as s:
        (await s.get(User, fix["user"]["Tool Engineer"]["id"])).is_active = False
        await s.commit()
    pm = await _auth(client, fix, "Project Manager")
    res = await _post_weight(client, pm, fix, 509.0, 518.0)
    assert res.status_code == 201, res.text
    res = await _post_weight(client, admin_auth, fix, 503.0, 509.0, **RETEST)
    assert res.status_code == 403, res.text


# --- an admin's department rows do not count for HARD #3 ---------------------

async def test_negative_admin_with_quality_and_check_rows_lifts_nothing(
        client, fix, admin_auth, session_factory):
    await _admin_in(session_factory, fix["dept"]["Quality"],
                    fix["dept"]["Tool Engineer"], fix["dept"]["Project Manager"])
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    st = await _state(client, admin_auth, fix)
    rights = {d["department_name"]: d["can_write"] for d in st["departments"]}
    assert rights["Tool Engineer"] is False
    issue = (await client.get(_iurl(fix, f"/{iid}"), headers=admin_auth)).json()
    assert "accept_deviation" not in issue.get("customer_options", [])
    for act in ("fix", "concession_request", "recheck"):
        assert act not in issue["next_acts"]
    res = await _post_weight(client, admin_auth, fix, 503.0, 509.0, **RETEST)
    assert res.status_code == 403, res.text
    res = await client.post(_iurl(fix, f"/{iid}/fix"), headers=admin_auth, json={
        "owner": "process_parameters",
        "retest_due": add_workdays(business_today(), 3).isoformat()})
    assert res.status_code == 403, res.text
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=admin_auth,
                            json={"note": "ask for 518 g max, 500 parts"})
    assert res.status_code == 403, res.text


# --- no route on a failed check, the concession is Quality's -----------------

async def test_negative_route_starts_no_concession_and_no_follow_up_on_a_failed_check(
        client, fix, admin_auth, session_factory):
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    pm = await _auth(client, fix, "Project Manager")
    res = await client.post(_iurl(fix, f"/{iid}/route"), headers=pm, json={
        "route": "customer_concession", "reason": "customer may accept"})
    assert res.status_code == 400, res.text
    assert "Request concession" in res.json()["detail"]
    # a follow-up change does not lift the failed check (no dead end)
    res = await client.post(_iurl(fix, f"/{iid}/route"), headers=pm, json={
        "route": "follow_up_change", "reason": "later", "actions": []})
    assert res.status_code == 400 and "HARD #3" in res.json()["detail"], res.text
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        assert c.status == "in_validation"
        i = await s.get(ValidationIssue, iid)
        assert i.route is None
    # an issue without a check: still no concession through /route
    res = await client.post(_iurl(fix), headers=pm, json={
        "title": "scratch on the cover", "description": "visual, 3 parts",
        "category": "other", "severity": 1,
        "department_id": fix["dept"]["Tool Engineer"]})
    assert res.status_code in (200, 201), res.text
    other = res.json()["id"]
    # the lead (the admin here; PM raised it, four eyes) is refused too
    res = await client.post(_iurl(fix, f"/{other}/route"), headers=admin_auth,
                            json={"route": "customer_concession", "reason": "ok"})
    assert res.status_code == 400, res.text
    assert "Request concession" in res.json()["detail"]


# --- an expired concession no longer covers the failed check -----------------

async def test_an_expired_concession_holds_the_release_again(
        client, fix, session_factory):
    async with session_factory() as s:
        (await s.get(ChangeRequest, fix["change_id"])).customer_relevant = False
        await s.commit()
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    quality = await _who(client, fix, "Quality")
    until = date.today() + timedelta(days=30)
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=quality, json={
        "note": "trial parts for the line test", "not_for_shipment": True,
        "concession_until": until.isoformat()})
    assert res.status_code == 200 and res.json()["status"] == "accepted", res.text
    from app.services.validation_service import ValidationService
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        failed, _ = await ValidationService.release_parts(s, c)
        assert failed is None
        await s.execute(update(ValidationIssue).where(ValidationIssue.id == iid)
                        .values(concession_until=business_today() - timedelta(days=5)))
        await s.commit()
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        failed, _ = await ValidationService.release_parts(s, c)
        assert failed is not None and failed.startswith("Validation failed")
    st = await _state(client, quality, fix)
    assert st["active_concessions"] == []
    expired = (business_today() - timedelta(days=5)).strftime("%a %d %b")
    assert f"concession VI-1 expired {expired}" in st["release_line"]
    pm = await _auth(client, fix, "Project Manager")
    res = await client.post(f"/api/v1/changes/{fix['change_id']}/transition",
                            headers=pm, json={"to_status": "released"})
    assert res.status_code in (400, 403, 409), res.text


# --- light Fix path: no route escalation, the right people told --------------

async def test_no_route_escalation_once_quality_picked_the_fix(
        client, fix, session_factory):
    from app.services.validation_issue_service import (
        ValidationIssueService, add_workdays,
    )
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    later = add_workdays(business_today(), 3)
    # no Fix pick for 2 working days: Quality's pick is what stalls
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        await ValidationIssueService.reevaluate(s, c, today=later)
        await s.rollback()
    await _pick_fix(client, fix, iid)
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        assert await ValidationIssueService.reevaluate(s, c, today=later) == 0
        await s.commit()
        rows = (await s.execute(select(ValidationIssueEscalation).where(
            ValidationIssueEscalation.issue_id == iid))).scalars().all()
    assert [r.level for r in rows] == [1]


async def test_no_fix_pick_escalates_as_no_fix_not_no_route(client, fix, session_factory):
    from app.services.validation_issue_service import (
        ValidationIssueService, add_workdays,
    )
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        await ValidationIssueService.reevaluate(
            s, c, today=add_workdays(business_today(), 3))
        await s.commit()
        rows = (await s.execute(select(ValidationIssueEscalation).where(
            ValidationIssueEscalation.issue_id == iid))).scalars().all()
    assert [(r.level, r.trigger) for r in rows] == [(1, "raised"), (2, "no_fix")]


async def test_fail_notice_reaches_quality_and_the_fix_pick_its_owners(
        client, fix, session_factory):
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    async with session_factory() as s:
        told = {n.user_id for n in (await s.execute(select(Notification).where(
            Notification.kind == "validation_issue_escalated"))).scalars()}
    assert fix["user"]["Quality"]["id"] in told
    assert fix["user"]["Project Manager"]["id"] not in told
    await _pick_fix(client, fix, iid)
    await _pick_fix(client, fix, iid)       # the same pick again: no second notice
    async with session_factory() as s:
        rows = (await s.execute(select(Notification).where(
            Notification.subject_key.like(f"vi:{iid}:fix:%")))).scalars().all()
    who = sorted(n.user_id for n in rows)
    assert who == sorted([fix["user"]["Process Engineer"]["id"],
                          fix["user"]["Tool Engineer"]["id"]])
    assert "retest" in rows[0].title


async def test_status_line_names_the_single_fixer(client, fix):
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    await _pick_fix(client, fix, iid)
    st = await _state(client, await _who(client, fix, "Quality"), fix)
    # fixture: Process Engineer's one member is named "Process Engineer"
    assert "fix: Process Engineer (Process Engineer), retest" in st["release_line"]
