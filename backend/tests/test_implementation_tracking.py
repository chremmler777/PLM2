"""Stage 8: implementation time tracking, the report cadence, escalations.

The rules under test are the ones that make 'in_implementation' more than a
status: who may book hours against which department, what "at least twice a
week" means to a scheduler, and what happens to an at-risk flag once Sales has
answered it.
"""
from datetime import datetime, timedelta

import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine, CostingPosition
from app.models.change_impl import ImplementationReport
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from app.auth.security import get_password_hash
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def impl(session_factory, seed):
    """A change in implementation with two implementing departments.

    Tool Engineer implements because it has a costing position; Development
    implements because it has a cost line — both routes into "this department
    priced work" are exercised. Assembly is routed but priced nothing, so it
    must NOT show up as implementing. Sales and Project Manager exist because
    the escalation and PM-override rules are named after them.
    """
    async with session_factory() as s:
        depts = {}
        for name, starter in [("Tool Engineer", False), ("Development", False),
                              ("Assembly", False), ("Sales", True),
                              ("Project Manager", False)]:
            d = Department(name=name, flow_type="action", is_active=True,
                           can_start_change=starter)
            s.add(d)
            await s.flush()
            depts[name] = d.id

        users = {}
        for name in ("Tool Engineer", "Development", "Assembly", "Sales",
                     "Project Manager"):
            email = f"{name.split()[0].lower()}@impl.test"
            u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                     email=email, full_name=name, role="engineer",
                     hashed_password=get_password_hash(ENGINEER_PASSWORD),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[name]))
            users[name] = {"id": u.id, "email": email}

        change = ChangeRequest(
            change_number="C-IMPL-1", title="implementation", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"],
            status="in_implementation")
        s.add(change)
        await s.flush()

        assessments = {}
        for name in ("Tool Engineer", "Development", "Assembly"):
            a = ChangeAssessment(change_id=change.id, department_id=depts[name],
                                 stage_order=1, verdict="feasible")
            s.add(a)
            await s.flush()
            assessments[name] = a.id

        # Tool Engineer priced through a costing position...
        s.add(CostingPosition(
            change_id=change.id, department_id=depts["Tool Engineer"],
            label="Tool rework", kind="external", pricing="estimate",
            est_cost=1000.0, created_by=seed["admin_id"]))
        # ...Development through a cost line on its assessment.
        s.add(AssessmentCostLine(
            assessment_id=assessments["Development"], plant_id=1,
            activity_label="CAD", cost_kind="one_time", demand_hours=4.0,
            rate_snapshot=65.0, internal_cost=260.0))
        await s.commit()
        return {"change_id": change.id, "dept": depts, "user": users,
                "assessments": assessments}


async def _auth(client, impl, name):
    return await login(client, impl["user"][name]["email"], ENGINEER_PASSWORD)


def _url(impl, suffix=""):
    return f"/api/v1/changes/{impl['change_id']}/implementation{suffix}"


async def _set_status(session_factory, change_id, status):
    async with session_factory() as s:
        change = await s.get(ChangeRequest, change_id)
        change.status = status
        await s.commit()


async def _backdate_reports(session_factory, change_id, hours):
    """Push every report on the change into the past. The cadence is a clock
    comparison, so the test moves the clock rather than sleeping on it."""
    from sqlalchemy import select
    when = datetime.utcnow() - timedelta(hours=hours)
    async with session_factory() as s:
        rows = (await s.execute(select(ImplementationReport).where(
            ImplementationReport.change_id == change_id))).scalars().all()
        for r in rows:
            r.reported_at = when
        await s.commit()


async def _actions(client, auth, change_id):
    res = await client.get(f"/api/v1/changes/{change_id}/changelog", headers=auth)
    assert res.status_code == 200, res.text
    return [e["action"] for e in res.json()]


async def _tasks(client, auth, kind=None):
    res = await client.get("/api/v1/changes/my-tasks", headers=auth)
    assert res.status_code == 200, res.text
    return [t for t in res.json() if kind is None or t["kind"] == kind]


async def _book(client, auth, impl, dept, hours=2.0, note=None):
    return await client.post(_url(impl, "/bookings"), headers=auth, json={
        "department_id": impl["dept"][dept], "hours": hours, "note": note})


async def _report(client, auth, impl, dept, note="on track", **kw):
    body = {"department_id": impl["dept"][dept], "note": note, **kw}
    return await client.post(_url(impl, "/reports"), headers=auth, json=body)


# --- bookings ---------------------------------------------------------------

async def test_department_books_its_own_hours(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    res = await _book(client, tool, impl, "Tool Engineer", hours=3.5,
                      note="fitting")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["hours"] == 3.5
    assert body["department_id"] == impl["dept"]["Tool Engineer"]
    assert body["booked_by"] == impl["user"]["Tool Engineer"]["id"]
    # The same author under the created_* naming, plus the name itself.
    assert body["created_by"] == body["booked_by"]
    assert body["created_at"] == body["booked_at"]
    assert body["created_by_name"] == "Tool Engineer"
    assert "implementation_time_booked" in await _actions(
        client, tool, impl["change_id"])


async def test_department_cannot_book_on_another_department(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    res = await _book(client, tool, impl, "Development")
    assert res.status_code == 403, res.text


async def test_pm_books_for_anyone(client, impl):
    pm = await _auth(client, impl, "Project Manager")
    res = await _book(client, pm, impl, "Development", hours=1.0)
    assert res.status_code == 201, res.text


async def test_booking_refused_outside_the_implementation_status(
        client, impl, session_factory):
    await _set_status(session_factory, impl["change_id"], "approved")
    tool = await _auth(client, impl, "Tool Engineer")
    res = await _book(client, tool, impl, "Tool Engineer")
    assert res.status_code == 403, res.text


async def test_non_implementing_department_cannot_book(client, admin_auth, impl):
    """Assembly was routed but never priced anything, so it is not on the
    hook — booking against it would put hours in a budget nobody opened."""
    res = await _book(client, admin_auth, impl, "Assembly")
    assert res.status_code == 400, res.text
    assert "not implementing" in res.json()["detail"]


async def test_bookings_are_department_scoped_for_readers(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    dev = await _auth(client, impl, "Development")
    sales = await _auth(client, impl, "Sales")
    assert (await _book(client, tool, impl, "Tool Engineer")).status_code == 201
    assert (await _book(client, dev, impl, "Development")).status_code == 201

    own = await client.get(_url(impl, "/bookings"), headers=tool)
    assert {b["department_id"] for b in own.json()} == {
        impl["dept"]["Tool Engineer"]}
    everything = await client.get(_url(impl, "/bookings"), headers=sales)
    assert {b["department_id"] for b in everything.json()} == {
        impl["dept"]["Tool Engineer"], impl["dept"]["Development"]}


async def test_booker_deletes_own_booking_but_not_a_colleagues(client, impl,
                                                               session_factory):
    tool = await _auth(client, impl, "Tool Engineer")
    pm = await _auth(client, impl, "Project Manager")
    mine = (await _book(client, tool, impl, "Tool Engineer")).json()["id"]
    theirs = (await _book(client, pm, impl, "Tool Engineer")).json()["id"]

    res = await client.delete(_url(impl, f"/bookings/{theirs}"), headers=tool)
    assert res.status_code == 403, res.text
    res = await client.delete(_url(impl, f"/bookings/{mine}"), headers=tool)
    assert res.status_code == 204, res.text
    assert "implementation_time_removed" in await _actions(
        client, tool, impl["change_id"])

    # And not once the stage is over.
    await _set_status(session_factory, impl["change_id"], "in_validation")
    res = await client.delete(_url(impl, f"/bookings/{theirs}"), headers=tool)
    assert res.status_code == 403, res.text


async def test_hours_must_be_positive(client, admin_auth, impl):
    res = await _book(client, admin_auth, impl, "Tool Engineer", hours=0)
    assert res.status_code == 422, res.text


# --- reports and the cadence ------------------------------------------------

async def test_report_round_trips_and_scopes(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    res = await _report(client, tool, impl, "Tool Engineer", note="mould in")
    assert res.status_code == 201, res.text
    assert res.json()["at_risk"] is False

    dev = await _auth(client, impl, "Development")
    assert (await _report(client, dev, impl, "Tool Engineer")).status_code == 403
    listed = await client.get(_url(impl, "/reports"), headers=dev)
    assert listed.json() == []


async def test_at_risk_without_a_risk_note_is_allowed(client, impl):
    """Recommended, never gated: making a department justify the flag in
    writing before it may raise it is how flags stop being raised."""
    tool = await _auth(client, impl, "Tool Engineer")
    res = await _report(client, tool, impl, "Tool Engineer",
                        note="steel late", at_risk=True)
    assert res.status_code == 201, res.text
    assert res.json()["at_risk"] is True
    assert res.json()["risk_note"] is None
    assert "implementation_risk_flagged" in await _actions(
        client, tool, impl["change_id"])


async def test_plain_report_logs_its_own_action(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    await _report(client, tool, impl, "Tool Engineer")
    actions = await _actions(client, tool, impl["change_id"])
    assert "implementation_reported" in actions
    assert "implementation_risk_flagged" not in actions


async def test_cadence_owes_a_report_until_one_arrives_and_again_after_84h(
        client, impl, session_factory):
    tool = await _auth(client, impl, "Tool Engineer")
    state = (await client.get(_url(impl, "/state"), headers=tool)).json()
    assert state["cadence_hours"] == 84
    row = state["departments"][0]
    assert row["owes_report"] is True and row["last_report_at"] is None

    await _report(client, tool, impl, "Tool Engineer")
    state = (await client.get(_url(impl, "/state"), headers=tool)).json()
    assert state["departments"][0]["owes_report"] is False

    # Inside the window (Monday -> Thursday) still fine; past it, owed again.
    await _backdate_reports(session_factory, impl["change_id"], 83)
    state = (await client.get(_url(impl, "/state"), headers=tool)).json()
    assert state["departments"][0]["owes_report"] is False

    await _backdate_reports(session_factory, impl["change_id"], 85)
    state = (await client.get(_url(impl, "/state"), headers=tool)).json()
    assert state["departments"][0]["owes_report"] is True


async def test_cadence_stops_outside_the_implementation_status(
        client, impl, session_factory):
    await _set_status(session_factory, impl["change_id"], "in_validation")
    tool = await _auth(client, impl, "Tool Engineer")
    state = (await client.get(_url(impl, "/state"), headers=tool)).json()
    assert all(d["owes_report"] is False for d in state["departments"])


async def test_progress_report_task_reaches_the_owing_department(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    rows = await _tasks(client, tool, "progress_report")
    assert len(rows) == 1
    assert rows[0]["department_id"] == impl["dept"]["Tool Engineer"]
    assert "twice a week" in rows[0]["hint"]

    await _report(client, tool, impl, "Tool Engineer")
    assert await _tasks(client, tool, "progress_report") == []

    # Assembly priced nothing, so it is never asked to report.
    assembly = await _auth(client, impl, "Assembly")
    assert await _tasks(client, assembly, "progress_report") == []


# --- escalations ------------------------------------------------------------

async def test_at_risk_raises_a_sales_escalation_task(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    sales = await _auth(client, impl, "Sales")
    assert await _tasks(client, sales, "escalate_risk") == []

    await _report(client, tool, impl, "Tool Engineer", at_risk=True,
                  risk_note="steel slipped two weeks")
    rows = await _tasks(client, sales, "escalate_risk")
    assert len(rows) == 1
    assert rows[0]["department_ids"] == [impl["dept"]["Tool Engineer"]]
    # The flagging department is not the one asked to escalate.
    assert await _tasks(client, tool, "escalate_risk") == []


async def test_only_sales_lead_or_admin_escalates(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    report_id = (await _report(client, tool, impl, "Tool Engineer",
                               at_risk=True)).json()["id"]
    body = {"direction": "customer", "note": "date moves", "report_id": report_id}
    res = await client.post(_url(impl, "/escalations"), json=body, headers=tool)
    assert res.status_code == 403, res.text

    sales = await _auth(client, impl, "Sales")
    res = await client.post(_url(impl, "/escalations"), json=body, headers=sales)
    assert res.status_code == 201, res.text
    assert res.json()["direction"] == "customer"
    assert res.json()["is_open"] is True
    assert "implementation_escalated" in await _actions(
        client, sales, impl["change_id"])


async def test_escalation_direction_is_validated(client, impl):
    sales = await _auth(client, impl, "Sales")
    res = await client.post(_url(impl, "/escalations"), headers=sales,
                            json={"direction": "sideways", "note": "n"})
    assert res.status_code == 400, res.text


async def test_escalating_clears_the_open_risk_and_resolving_closes_it(
        client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    sales = await _auth(client, impl, "Sales")
    report_id = (await _report(client, tool, impl, "Tool Engineer",
                               at_risk=True)).json()["id"]
    state = (await client.get(_url(impl, "/state"), headers=sales)).json()
    assert [d["at_risk_open"] for d in state["departments"]] == [True, False]

    eid = (await client.post(_url(impl, "/escalations"), headers=sales, json={
        "direction": "internal", "note": "re-plan around it",
        "report_id": report_id})).json()["id"]
    state = (await client.get(_url(impl, "/state"), headers=sales)).json()
    assert all(d["at_risk_open"] is False for d in state["departments"])
    assert state["open_escalations"] == 1
    assert await _tasks(client, sales, "escalate_risk") == []

    res = await client.put(_url(impl, f"/escalations/{eid}/resolve"),
                           headers=sales, json={"resolution_note": "absorbed"})
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False
    assert res.json()["resolution_note"] == "absorbed"
    assert "escalation_resolved" in await _actions(
        client, sales, impl["change_id"])

    # Resolving twice is not a second answer.
    res = await client.put(_url(impl, f"/escalations/{eid}/resolve"),
                           headers=sales, json={"resolution_note": "again"})
    assert res.status_code == 400, res.text

    # A NEW flag after the answer re-opens the risk — the loop is per flag,
    # not per change.
    await _report(client, tool, impl, "Tool Engineer", at_risk=True,
                  note="slipped again")
    state = (await client.get(_url(impl, "/state"), headers=sales)).json()
    assert state["departments"][0]["at_risk_open"] is True
    assert len(await _tasks(client, sales, "escalate_risk")) == 1


async def test_a_resolution_clears_the_open_risk(client, impl):
    """The escalation loop closing is an answer, not just its opening."""
    tool = await _auth(client, impl, "Tool Engineer")
    sales = await _auth(client, impl, "Sales")
    report_id = (await _report(client, tool, impl, "Tool Engineer",
                               at_risk=True)).json()["id"]
    eid = (await client.post(_url(impl, "/escalations"), headers=sales, json={
        "direction": "customer", "note": "date moves",
        "report_id": report_id})).json()["id"]
    res = await client.put(_url(impl, f"/escalations/{eid}/resolve"),
                           headers=sales,
                           json={"resolution_note": "customer accepted week 38"})
    assert res.status_code == 200, res.text
    assert res.json()["resolved_by_name"] == "Sales"
    state = (await client.get(_url(impl, "/state"), headers=sales)).json()
    assert all(d["at_risk_open"] is False for d in state["departments"])
    assert state["open_escalations"] == 0
    assert await _tasks(client, sales, "escalate_risk") == []


async def test_a_newer_clean_report_clears_the_open_risk(client, impl):
    """The department owns the other half of the loop: its LATEST report is
    its current position. "Back on track" retracts the flag without anybody
    having to escalate anything."""
    tool = await _auth(client, impl, "Tool Engineer")
    sales = await _auth(client, impl, "Sales")
    await _report(client, tool, impl, "Tool Engineer", at_risk=True,
                  note="steel late")
    state = (await client.get(_url(impl, "/state"), headers=sales)).json()
    assert state["departments"][0]["at_risk_open"] is True

    await _report(client, tool, impl, "Tool Engineer", note="steel arrived")
    state = (await client.get(_url(impl, "/state"), headers=sales)).json()
    assert state["departments"][0]["at_risk_open"] is False
    assert state["departments"][0]["report_count"] == 2
    assert await _tasks(client, sales, "escalate_risk") == []


async def test_escalation_resolution_note_is_required(client, impl):
    sales = await _auth(client, impl, "Sales")
    eid = (await client.post(_url(impl, "/escalations"), headers=sales, json={
        "direction": "customer", "note": "told them"})).json()["id"]
    res = await client.put(_url(impl, f"/escalations/{eid}/resolve"),
                           headers=sales, json={"resolution_note": "  "})
    assert res.status_code == 400, res.text


async def test_escalations_are_visible_to_the_flagging_department(client, impl):
    sales = await _auth(client, impl, "Sales")
    await client.post(_url(impl, "/escalations"), headers=sales,
                      json={"direction": "customer", "note": "told them"})
    tool = await _auth(client, impl, "Tool Engineer")
    listed = await client.get(_url(impl, "/escalations"), headers=tool)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1


# --- the state payload ------------------------------------------------------

async def test_state_payload_shape_and_totals(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    pm = await _auth(client, impl, "Project Manager")
    await _book(client, tool, impl, "Tool Engineer", hours=3.0)
    await _book(client, tool, impl, "Tool Engineer", hours=1.5)
    await _book(client, pm, impl, "Development", hours=2.0)

    res = await client.get(_url(impl, "/state"), headers=pm)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["change_id"] == impl["change_id"]
    assert body["status"] == "in_implementation"
    assert body["total_booked_hours"] == 6.5
    assert body["open_escalations"] == 0
    # Only the departments that priced work, sorted by department id.
    ids = [d["department_id"] for d in body["departments"]]
    assert ids == sorted([impl["dept"]["Tool Engineer"],
                          impl["dept"]["Development"]])
    by_id = {d["department_id"]: d for d in body["departments"]}
    assert by_id[impl["dept"]["Tool Engineer"]]["booked_hours"] == 4.5
    assert by_id[impl["dept"]["Development"]]["booked_hours"] == 2.0
    assert set(body["departments"][0]) == {
        "department_id", "department_name", "booked_hours", "report_count",
        "last_report_at", "at_risk_open", "owes_report"}


async def test_state_is_scoped_to_the_callers_department(client, impl):
    tool = await _auth(client, impl, "Tool Engineer")
    body = (await client.get(_url(impl, "/state"), headers=tool)).json()
    assert [d["department_id"] for d in body["departments"]] == [
        impl["dept"]["Tool Engineer"]]
    # The total follows the scope: a department must not be able to read the
    # programme's hours out of a number it is allowed to see.
    assert body["total_booked_hours"] == 0.0
