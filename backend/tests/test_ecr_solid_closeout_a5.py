"""ECR-solid close-out of area 5 (release / validation / close / hours).
Each test names the finding it pins (A5-nn); permission items carry a
negative test.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.change_validation_issue import ValidationIssue
from tests.test_ecr_solid_fix_concession import (  # noqa: F401
    _fail_weight, _issue, _iurl, _kinds, _who, fix,
)
from tests.test_validation_checks import _auth, _url, val  # noqa: F401

pytestmark = pytest.mark.asyncio

GOOD_REF = "re-measured on CMM, report MR-2026-311"


async def _unlinked(client, fix, auth, dept="Tool Engineer"):
    res = await client.post(_iurl(fix), headers=auth, json={
        "title": "scratch on the cover", "description": "visual, 3 parts",
        "category": "other", "severity": 1, "check_id": None,
        "department_id": fix["dept"][dept]})
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _to_revalidation(client, fix, iid, admin_auth, router):
    res = await client.post(_iurl(fix, f"/{iid}/root-cause"), headers=admin_auth,
                            json={"root_cause": "Gripper scratched the cover"})
    assert res.status_code == 200, res.text
    res = await client.post(_iurl(fix, f"/{iid}/route"), headers=router, json={
        "route": "internal_rework", "reason": "Rework the gripper pads",
        "actions": [{"description": "Change the gripper pads"}]})
    assert res.status_code == 200, res.text
    aid = res.json()["actions"][0]["id"]
    res = await client.post(_iurl(fix, f"/{iid}/actions/{aid}/done"), headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "revalidation"


# --- A5-01 an unlinked issue is cleared by Quality with evidence --------------

async def test_a5_01_negative_admin_alone_cannot_route_its_own_issue(
        client, fix, admin_auth):
    iid = await _unlinked(client, fix, admin_auth)
    await client.post(_iurl(fix, f"/{iid}/root-cause"), headers=admin_auth,
                      json={"root_cause": "Gripper scratched the cover"})
    res = await client.post(_iurl(fix, f"/{iid}/route"), headers=admin_auth, json={
        "route": "internal_rework", "reason": "Rework the gripper pads",
        "actions": [{"description": "Change the gripper pads"}]})
    assert res.status_code == 403 and "Four eyes" in res.json()["detail"], res.text
    out = (await client.get(_iurl(fix, f"/{iid}"), headers=admin_auth)).json()
    assert "route" not in out["next_acts"]


async def test_a5_01_negative_close_from_revalidation_is_qualitys_with_a_reference(
        client, fix, admin_auth, session_factory):
    iid = await _unlinked(client, fix, admin_auth)
    pm = await _auth(client, fix, "Project Manager")
    await _to_revalidation(client, fix, iid, admin_auth, pm)
    # an admin alone, PM and the lead (admin here) are refused, any note
    for auth in (admin_auth, pm):
        for note in ("ok", GOOD_REF):
            res = await client.post(_iurl(fix, f"/{iid}/close"), headers=auth,
                                    json={"note": note})
            assert res.status_code == 403, res.text
        out = (await client.get(_iurl(fix, f"/{iid}"), headers=auth)).json()
        assert "close" not in out["next_acts"]
    quality = await _who(client, fix, "Quality")
    out = (await client.get(_iurl(fix, f"/{iid}"), headers=quality)).json()
    assert "close" in out["next_acts"] and out["close_needs_ref"] is True
    tasks = await _kinds(client, quality, fix["change_id"])
    assert "validation_issue_close" in tasks
    res = await client.post(_iurl(fix, f"/{iid}/close"), headers=quality,
                            json={"note": "ok"})
    assert res.status_code == 400, res.text                      # NEGATIVE
    # the owner department may confirm its own fix too, with the evidence
    tool = await _auth(client, fix, "Tool Engineer")
    assert "close" in (await client.get(_iurl(fix, f"/{iid}"), headers=tool)).json()["next_acts"]
    res = await client.post(_iurl(fix, f"/{iid}/close"), headers=quality,
                            json={"note": GOOD_REF})
    assert res.status_code == 200 and res.json()["status"] == "closed", res.text


async def test_a5_01_negative_follow_up_on_an_open_issue_is_qualitys(
        client, fix, admin_auth):
    iid = await _unlinked(client, fix, await _auth(client, fix, "Tool Engineer"))
    await client.post(_iurl(fix, f"/{iid}/root-cause"), headers=admin_auth,
                      json={"root_cause": "Gripper scratched the cover"})
    body = {"route": "follow_up_change", "reason": "Gripper redesign is its own change"}
    pm = await _auth(client, fix, "Project Manager")
    for auth in (pm, admin_auth):
        res = await client.post(_iurl(fix, f"/{iid}/route"), headers=auth, json=body)
        assert res.status_code == 403, res.text                  # NEGATIVE
    out = (await client.get(_iurl(fix, f"/{iid}"), headers=pm)).json()
    assert "follow_up_change" not in out["route_options"]
    quality = await _who(client, fix, "Quality")
    out = (await client.get(_iurl(fix, f"/{iid}"), headers=quality)).json()
    assert out["route_options"] == ["follow_up_change"] and "route" in out["next_acts"]
    assert out["primary_act"] is None          # options: the run team routes the fix
    # A5-08: Quality is offered the raised-in-error close; PM is not
    assert "close" in out["next_acts"]
    assert "close" not in (await client.get(_iurl(fix, f"/{iid}"), headers=pm)).json()["next_acts"]
    # Quality's follow-up pick is an option, not a task
    assert "validation_issue_route" not in await _kinds(client, quality, fix["change_id"])
    res = await client.post(_iurl(fix, f"/{iid}/route"), headers=quality, json=body)
    assert res.status_code == 200 and res.json()["status"] == "transferred", res.text


# --- A5-02 the measurer's own limits: a PASS counts after Quality confirms ----

SPEC = {"lower_limit": 480.0, "upper_limit": 530.0,
        "spec_source": "drawing 886.197 D, weight 505 g +/-25"}


async def _weigh(client, fix, lo=505.0, hi=512.0, spec=SPEC):
    tool = await _auth(client, fix, "Tool Engineer")
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": lo, "max_value": hi,
                        "measuring_ref": "scale WG-0042, report MR-2026-118", **spec}})
    assert res.status_code == 201, res.text
    return res.json()


async def _weight_row(client, fix, auth):
    state = (await client.get(_url(fix, "/state"), headers=auth)).json()
    dept = next(d for d in state["departments"]
                if d["department_id"] == fix["dept"]["Tool Engineer"])
    return state, next(c for c in dept["checks"] if c["check_key"] == "weight")


async def test_a5_02_negative_own_limits_do_not_make_a_pass_count(
        client, fix, admin_auth):
    row = await _weigh(client, fix)
    assert row["status"] == "passed"
    tool = await _auth(client, fix, "Tool Engineer")
    state, chk = await _weight_row(client, fix, tool)
    assert chk["limits_pending"] is True and chk["limits_set_by_name"] == "Tool Engineer"
    assert chk["can_confirm_limits"] is False
    assert "limits set by Tool Engineer: Quality confirms" in state["release_blocker"]
    url = _url(fix, f"/checks/{chk['check_id']}/limits")
    # NEGATIVE: the setter, an admin alone and PM (Quality is staffed) cannot
    for auth in (tool, admin_auth, await _auth(client, fix, "Project Manager")):
        res = await client.post(url, headers=auth, json={})
        assert res.status_code == 403, res.text
    quality = await _who(client, fix, "Quality")
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=quality)).json()
    row = next(t for t in tasks if t["change_id"] == fix["change_id"]
               and t["kind"] == "validation_check")
    assert row["needs_you"] and "Confirm the limits of" in row["reason"]
    assert "set by Tool Engineer" in row["reason"]
    _, chk = await _weight_row(client, fix, quality)
    assert chk["can_confirm_limits"] is True
    res = await client.post(url, headers=quality, json={})
    assert res.status_code == 200 and res.json()["status"] == "passed", res.text
    state, chk = await _weight_row(client, fix, quality)
    assert chk["limits_pending"] is False and chk["limits_confirmed_by_name"] == "Quality"
    assert "limits set by" not in (state["release_blocker"] or "")
    # once confirmed, there is nothing left to confirm
    assert (await client.post(url, headers=quality, json={})).status_code == 400


async def test_a5_02_quality_corrects_wide_limits_and_the_fail_counts(client, fix):
    await _weigh(client, fix, lo=505.0, hi=528.0)
    quality = await _who(client, fix, "Quality")
    _, chk = await _weight_row(client, fix, quality)
    url = _url(fix, f"/checks/{chk['check_id']}/limits")
    res = await client.post(url, headers=quality, json={
        "lower_limit": 495, "upper_limit": 515, "spec_source": "ok"})
    assert res.status_code == 400                                 # NEGATIVE
    res = await client.post(url, headers=quality, json={
        "lower_limit": 495, "upper_limit": 515,
        "spec_source": "drawing 886.197 D, weight 505 g +/-10"})
    assert res.status_code == 200 and res.json()["status"] == "failed", res.text
    issue = await _issue(client, fix)                              # HARD #3 holds
    assert issue["check_key"] == "weight"



# --- A5-04 the member-less department fallback, complete and worded once ----

from app.models.entities import User  # noqa: E402
from app.models.workflow import UserDepartment  # noqa: E402


async def _memberless(session_factory, fix, *names, lead="Project Manager"):
    async with session_factory() as s:
        for n in names:
            (await s.get(User, fix["user"][n]["id"])).is_active = False
        (await s.get(ChangeRequest, fix["change_id"])).lead_id = fix["user"][lead]["id"]
        await s.commit()


async def test_a5_04a_negative_the_lead_gets_the_checks_of_a_memberless_department(
        client, fix, session_factory):
    await _memberless(session_factory, fix, "Tool Engineer")
    pm = await _auth(client, fix, "Project Manager")
    tasks = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=pm)).json()
             if t["change_id"] == fix["change_id"] and t["kind"] == "validation_check"]
    by_dept = {t["department_id"]: t for t in tasks}
    tool = by_dept[fix["dept"]["Tool Engineer"]]
    assert tool["reason"] == ("Tool Engineer has no member here: Project Manager "
                              "coordinates: answer its checks")
    assert tool["due_date"] is not None
    # NEGATIVE: a staffed department's checks stay its own
    assert fix["dept"]["Development"] not in by_dept
    state = (await client.get(_url(fix, "/state"), headers=pm)).json()
    hint = {d["department_name"]: d.get("no_member_hint") for d in state["departments"]}
    assert hint["Tool Engineer"] == "Tool Engineer has no member here: Project Manager coordinates"
    assert hint["Development"] is None


async def test_a5_04b_negative_the_lead_books_hours_for_a_memberless_department(
        client, fix, session_factory):
    await _memberless(session_factory, fix, "Tool Engineer")
    pm = await _auth(client, fix, "Project Manager")
    url = f"/api/v1/changes/{fix['change_id']}/hours"
    res = await client.post(url, headers=pm, json={
        "department_id": fix["dept"]["Development"], "hours": 2})
    assert res.status_code == 403, res.text                       # NEGATIVE
    res = await client.post(url, headers=pm, json={
        "department_id": fix["dept"]["Tool Engineer"], "hours": 3})
    assert res.status_code in (200, 201), res.text
    state = (await client.get(url, headers=pm)).json()
    mine = {m["department_id"]: m for m in state["mine"]}
    assert mine[fix["dept"]["Tool Engineer"]]["no_member"] is True
    assert "no member here: Project Manager coordinates" in \
        mine[fix["dept"]["Tool Engineer"]]["source_label"]
    row = next(b for b in state["bookings"] if b["department_id"] == fix["dept"]["Tool Engineer"])
    assert row["booked_by_name"] == "Project Manager"


async def test_a5_04c_one_person_owes_fix_and_retest_one_row_fix_first(
        client, fix, session_factory):
    async with session_factory() as s:
        s.add(UserDepartment(user_id=fix["user"]["Tool Engineer"]["id"],
                             department_id=fix["dept"]["Process Engineer"]))
        await s.commit()
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    due = date.today() + timedelta(days=3)
    res = await client.post(_iurl(fix, f"/{iid}/fix"), headers=await _who(client, fix, "Quality"),
                            json={"owner": "process_parameters", "retest_due": due.isoformat()})
    assert res.status_code == 200, res.text
    tool = await _auth(client, fix, "Tool Engineer")
    tasks = await _kinds(client, tool, fix["change_id"])
    assert "validation_issue_fix_work" not in tasks
    assert tasks["validation_issue_recheck"]["label"] == (
        f"Fix VI-1, then retest by {due.strftime('%a %d %b')}")


async def test_a5_04c_the_coordinator_reads_get_the_fixer_then_retest(
        client, fix, session_factory):
    await _memberless(session_factory, fix, "Tool Engineer", "Process Engineer")
    # PM measures for the member-less Tool Engineer (it coordinates)
    pm = await _auth(client, fix, "Project Manager")
    res = await client.post(_url(fix, "/checks"), headers=pm, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 509.0, "max_value": 518.0,
                        "measuring_ref": "scale WG-0042, report MR-2026-118",
                        "lower_limit": 495.0, "upper_limit": 515.0,
                        "spec_source": "drawing 886.197 D, weight 505 g +/-10"}})
    assert res.status_code == 201 and res.json()["status"] == "failed", res.text
    iid = (await _issue(client, fix))["id"]
    due = date.today() + timedelta(days=3)
    await client.post(_iurl(fix, f"/{iid}/fix"), headers=await _who(client, fix, "Quality"),
                      json={"owner": "process_parameters", "retest_due": due.isoformat()})
    tasks = await _kinds(client, pm, fix["change_id"])
    assert "validation_issue_fix_work" not in tasks
    label = tasks["validation_issue_recheck"]["label"]
    assert label.startswith(f"Get Process Engineer to fix VI-1, then retest by {due.strftime('%a %d %b')}")
    assert label.endswith("(Tool Engineer has no member here: Project Manager coordinates)")
    st = (await client.get(_url(fix, "/state"), headers=pm)).json()
    assert "fix: Process Engineer (no member here: Project Manager coordinates), retest " \
        f"{due.strftime('%a %d %b')}" in st["release_line"]
