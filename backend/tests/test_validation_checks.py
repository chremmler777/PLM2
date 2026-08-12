"""Stage 9: the validation checks, the weight delta, and the release verdict.

The rules under test are the ones that turn 'in_validation' from a waiting room
into a decision: which checks each implementing department owes, who may sign
them, what a measured weight does to the quote, when the release guard refuses,
and what sending the change back round the loop has to say for itself.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeRequest
from app.models.change_cost import (
    AssessmentCostLine, CostingPosition, DepartmentRate,
)
from app.models.change import ChangeAssessment
from app.models.change_validation import ValidationCheck
from app.models.entities import Project, User
from app.models.workflow import Department, UserDepartment
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def val(session_factory, seed):
    """A change in validation with two implementing departments.

    Tool Engineer implements through a costing position, Development through a
    cost line — the same two routes stage 8 derives from, so the checklist and
    the progress view can never disagree about who is on the hook. Assembly is
    routed but priced nothing and must never appear. Development's line is a
    LIFECYCLE line carrying minutes per part, which is the costing assumption
    the measured cycle time is held against.

    Tool Engineer has a rate at the plant and Development deliberately does
    not: the actuals P&L has to report the missing rate rather than invent one.
    """
    async with session_factory() as s:
        project = await s.get(Project, seed["project_id"])
        plant_id = project.plant_id
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
            email = f"{name.split()[0].lower()}@val.test"
            u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                     email=email, full_name=name, role="engineer",
                     hashed_password=get_password_hash(ENGINEER_PASSWORD),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[name]))
            users[name] = {"id": u.id, "email": email}

        s.add(DepartmentRate(department_id=depts["Tool Engineer"],
                             plant_id=plant_id, hourly_rate=100.0))

        change = ChangeRequest(
            change_number="C-VAL-1", title="validation", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"],
            status="in_validation", estimated_part_weight_g=500.0,
            # The loop back to implementation re-runs that stage's own guard;
            # the impacted set was locked long before validation in any real
            # flow, so the fixture says so rather than testing stage 6 again.
            impact_confirmed_at=datetime.utcnow(),
            impact_confirmed_by=seed["admin_id"])
        s.add(change)
        await s.flush()

        assessments = {}
        for name in ("Tool Engineer", "Development", "Assembly"):
            a = ChangeAssessment(change_id=change.id, department_id=depts[name],
                                 stage_order=1, verdict="feasible")
            s.add(a)
            await s.flush()
            assessments[name] = a.id

        s.add(CostingPosition(
            change_id=change.id, department_id=depts["Tool Engineer"],
            label="Tool rework", kind="external", pricing="estimate",
            est_cost=1000.0, created_by=seed["admin_id"]))
        s.add(AssessmentCostLine(
            assessment_id=assessments["Development"], plant_id=plant_id,
            activity_label="Cycle time", cost_kind="lifecycle",
            demand_hours=4.0, rate_snapshot=65.0, internal_cost=260.0,
            minutes_per_part=0.5))
        await s.commit()
        return {"change_id": change.id, "dept": depts, "user": users,
                "plant_id": plant_id, "assessments": assessments}


async def _auth(client, val, name):
    return await login(client, val["user"][name]["email"], ENGINEER_PASSWORD)


def _url(val, suffix=""):
    return f"/api/v1/changes/{val['change_id']}/validation{suffix}"


async def _state(client, auth, val):
    res = await client.get(_url(val, "/state"), headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _check(client, auth, val, dept, key, status="passed", **kw):
    return await client.post(_url(val, "/checks"), headers=auth, json={
        "department_id": val["dept"][dept], "check_key": key,
        "status": status, **kw})


async def _pass_all(client, auth, val, skip=()):
    """Sign off everything the catalog asks of both departments."""
    state = await _state(client, auth, val)
    for dept in state["departments"]:
        name = dept["department_name"]
        for check in dept["checks"]:
            if check["check_key"] in skip:
                continue
            value = {"cycle_time": 41.5, "weight": 510.0}.get(check["check_key"])
            res = await _check(client, auth, val, name, check["check_key"],
                               value=value)
            assert res.status_code == 201, res.text


async def _actions(client, auth, change_id):
    res = await client.get(f"/api/v1/changes/{change_id}/changelog", headers=auth)
    assert res.status_code == 200, res.text
    return [e["action"] for e in res.json()]


async def _tasks(client, auth, kind=None):
    res = await client.get("/api/v1/changes/my-tasks", headers=auth)
    assert res.status_code == 200, res.text
    return [t for t in res.json() if kind is None or t["kind"] == kind]


async def _set_status(session_factory, change_id, status):
    async with session_factory() as s:
        change = await s.get(ChangeRequest, change_id)
        change.status = status
        await s.commit()


# --- the catalog ------------------------------------------------------------

async def test_catalog_is_per_department_and_only_for_implementers(
        client, admin_auth, val):
    state = await _state(client, admin_auth, val)
    by_name = {d["department_name"]: d for d in state["departments"]}
    assert set(by_name) == {"Tool Engineer", "Development"}

    tool_keys = [c["check_key"] for c in by_name["Tool Engineer"]["checks"]]
    assert tool_keys == ["sampled", "measured", "cycle_time", "weight"]
    dev_keys = [c["check_key"] for c in by_name["Development"]["checks"]]
    assert dev_keys == ["sampled", "measured", "cycle_time", "revision_bump"]

    # The two measurements declare their unit; the yes/no checks do not.
    units = {c["check_key"]: (c["expects_value"], c["unit"])
             for d in state["departments"] for c in d["checks"]}
    assert units["cycle_time"] == (True, "seconds")
    assert units["weight"] == (True, "grams")
    assert units["sampled"] == (False, None)
    assert units["revision_bump"] == (False, None)

    assert state["all_passed"] is False
    assert state["open_count"] == state["check_count"] == 8


async def test_state_carries_the_costing_assumptions_to_compare_against(
        client, admin_auth, val):
    state = await _state(client, admin_auth, val)
    by_name = {d["department_name"]: d for d in state["departments"]}
    dev_cycle = next(c for c in by_name["Development"]["checks"]
                     if c["check_key"] == "cycle_time")
    # 0.5 min/part of lifecycle cost line = 30 s the costing priced in.
    assert dev_cycle["planned_delta_seconds"] == 30.0
    # Tool Engineer priced no lifecycle minutes: no assumption is not zero.
    tool_cycle = next(c for c in by_name["Tool Engineer"]["checks"]
                      if c["check_key"] == "cycle_time")
    assert tool_cycle["planned_delta_seconds"] is None

    # Change-wide, in the unit the COSTING states it: minutes per part.
    assert state["planned_cycle_time_min_per_part"] == 0.5

    weight = next(c for c in by_name["Tool Engineer"]["checks"]
                  if c["check_key"] == "weight")
    assert weight["estimated_part_weight_g"] == 500.0
    assert weight["delta_g"] is None      # nothing weighed yet
    # The flat weight fields the card reads, before anything is weighed.
    assert state["weight_estimate_g"] == 500.0
    assert state["validated_weight_g"] is None
    assert state["weight_delta_g"] is None
    assert state["weight_ack_at"] is None


async def test_rows_are_seeded_once_however_often_the_state_is_read(
        client, admin_auth, val, session_factory):
    await _state(client, admin_auth, val)
    await _state(client, admin_auth, val)
    async with session_factory() as s:
        rows = (await s.execute(select(ValidationCheck).where(
            ValidationCheck.change_id == val["change_id"]))).scalars().all()
    assert len(rows) == 8
    assert all(r.status == "open" and r.checked_by is None for r in rows)


# --- who may sign -----------------------------------------------------------

async def test_department_signs_its_own_checks_only(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    res = await _check(client, tool, val, "Tool Engineer", "sampled")
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "passed"
    assert "validation_check" in await _actions(client, tool, val["change_id"])

    res = await _check(client, tool, val, "Development", "sampled")
    assert res.status_code == 403, res.text


async def test_pm_signs_for_anyone_and_admin_ignores_the_status_window(
        client, admin_auth, val, session_factory):
    pm = await _auth(client, val, "Project Manager")
    assert (await _check(client, pm, val, "Development",
                         "sampled")).status_code == 201

    await _set_status(session_factory, val["change_id"], "in_implementation")
    tool = await _auth(client, val, "Tool Engineer")
    res = await _check(client, tool, val, "Tool Engineer", "measured")
    assert res.status_code == 403, res.text
    assert (await _check(client, admin_auth, val, "Tool Engineer",
                         "measured")).status_code == 201


async def test_a_department_cannot_sign_a_check_it_does_not_own(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    res = await _check(client, tool, val, "Tool Engineer", "revision_bump")
    assert res.status_code == 400, res.text
    assert "not a validation check" in res.json()["detail"]


async def test_non_implementing_department_has_no_checks(client, admin_auth, val):
    res = await client.post(_url(val, "/checks"), headers=admin_auth, json={
        "department_id": val["dept"]["Assembly"], "check_key": "sampled",
        "status": "passed"})
    assert res.status_code == 400, res.text
    assert "not implementing" in res.json()["detail"]


async def test_measurements_need_their_number_to_pass(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    res = await _check(client, tool, val, "Tool Engineer", "cycle_time")
    assert res.status_code == 400, res.text
    assert "seconds" in res.json()["detail"]
    # Failing one does not: "we measured nothing usable" is a real answer.
    assert (await _check(client, tool, val, "Tool Engineer", "cycle_time",
                         status="failed")).status_code == 201
    res = await _check(client, tool, val, "Tool Engineer", "cycle_time",
                       value=42.25)
    assert res.status_code == 201, res.text
    # Seconds in, seconds out — stored exactly as measured, never converted
    # into the costing's minutes-per-part on the way in.
    assert res.json()["value"] == 42.25
    state = await _state(client, tool, val)
    stored = next(c for d in state["departments"] for c in d["checks"]
                  if c["check_key"] == "cycle_time"
                  and d["department_name"] == "Tool Engineer")
    assert (stored["value"], stored["unit"]) == (42.25, "seconds")


# --- the weight, and the quote it moves -------------------------------------

async def test_weight_pass_stamps_the_change_and_raises_the_sales_task(
        client, val, session_factory):
    tool = await _auth(client, val, "Tool Engineer")
    sales = await _auth(client, val, "Sales")
    assert await _tasks(client, sales, "update_quote") == []

    res = await _check(client, tool, val, "Tool Engineer", "weight", value=530.0)
    assert res.status_code == 201, res.text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, val["change_id"])
        assert change.validated_part_weight_g == 530.0
        assert change.validated_weight_by == val["user"]["Tool Engineer"]["id"]
        assert change.validated_weight_at is not None
    assert "weight_validated" in await _actions(client, tool, val["change_id"])

    state = await _state(client, tool, val)
    assert state["weight_estimate_g"] == 500.0
    assert state["validated_weight_g"] == 530.0
    # The delta is computed backend-side; no client ever subtracts these.
    assert state["weight_delta_g"] == 30.0
    assert state["weight_quote_update_open"] is True

    rows = await _tasks(client, sales, "update_quote")
    assert len(rows) == 1
    assert rows[0]["delta_g"] == 30.0
    assert "+30 g" in rows[0]["hint"]
    # It is Sales' errand, not the tool shop's.
    assert await _tasks(client, tool, "update_quote") == []


async def test_matching_weight_raises_nothing(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    sales = await _auth(client, val, "Sales")
    await _check(client, tool, val, "Tool Engineer", "weight", value=500.0)
    assert await _tasks(client, sales, "update_quote") == []
    state = await _state(client, tool, val)
    assert state["weight_delta_g"] == 0.0
    assert state["weight_quote_update_open"] is False


async def test_sales_acknowledges_the_delta_and_the_task_clears(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    sales = await _auth(client, val, "Sales")
    dev = await _auth(client, val, "Development")
    await _check(client, tool, val, "Tool Engineer", "weight", value=530.0)

    # Not the tool shop's decision to make.
    res = await client.post(_url(val, "/weight-ack"), headers=dev, json={})
    assert res.status_code == 403, res.text

    res = await client.post(_url(val, "/weight-ack"), headers=sales,
                            json={"note": "re-quoted at +30 g"})
    assert res.status_code == 200, res.text
    assert res.json()["weight_delta_ack_at"] is not None
    state = await _state(client, sales, val)
    assert state["weight_ack_at"] is not None
    assert state["weight_ack_by_name"] == "Sales"
    assert state["weight_ack_note"] == "re-quoted at +30 g"
    assert await _tasks(client, sales, "update_quote") == []
    assert "weight_delta_acknowledged" in await _actions(
        client, sales, val["change_id"])

    # Once only.
    res = await client.post(_url(val, "/weight-ack"), headers=sales, json={})
    assert res.status_code == 400, res.text


async def test_a_new_weight_reopens_the_commercial_question(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    sales = await _auth(client, val, "Sales")
    await _check(client, tool, val, "Tool Engineer", "weight", value=530.0)
    await client.post(_url(val, "/weight-ack"), headers=sales, json={})
    assert await _tasks(client, sales, "update_quote") == []

    await _check(client, tool, val, "Tool Engineer", "weight", value=560.0)
    rows = await _tasks(client, sales, "update_quote")
    assert len(rows) == 1 and rows[0]["delta_g"] == 60.0


async def test_ack_refused_when_there_is_no_delta(client, val):
    sales = await _auth(client, val, "Sales")
    res = await client.post(_url(val, "/weight-ack"), headers=sales, json={})
    assert res.status_code == 400, res.text
    assert "not been both estimated and validated" in res.json()["detail"]


# --- the release verdict ----------------------------------------------------

async def _release(client, auth, val):
    return await client.post(
        f"/api/v1/changes/{val['change_id']}/transition", headers=auth,
        json={"to_status": "released"})


async def test_release_refused_while_checks_are_open(client, admin_auth, val):
    await _state(client, admin_auth, val)          # seeds the rows
    res = await _release(client, admin_auth, val)
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert "validation incomplete" in detail
    # The message NAMES what is missing, department by check.
    assert "Tool Engineer: Part weight validated" in detail


async def test_release_refused_when_a_check_failed(client, admin_auth, val):
    await _pass_all(client, admin_auth, val, skip={"revision_bump"})
    await _check(client, admin_auth, val, "Development", "revision_bump",
                 status="failed", note="customer statement says rev D")
    res = await _release(client, admin_auth, val)
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert "validation failed" in detail
    assert "Development: Revision levels raised" in detail

    state = await _state(client, admin_auth, val)
    assert state["failed_count"] == 1
    # The guard refuses with exactly the blocker string, plus the standard
    # deviation postscript every soft guard adds.
    assert detail.startswith(state["release_blocker"])


async def test_release_passes_the_validation_guard_once_everything_is_signed(
        client, admin_auth, val):
    await _pass_all(client, admin_auth, val)
    state = await _state(client, admin_auth, val)
    assert state["all_passed"] is True
    assert state["release_blocker"] is None
    # The remaining refusal is the pre-existing ready-to-go gate, not ours.
    res = await _release(client, admin_auth, val)
    assert res.status_code == 400, res.text
    assert "validation" not in res.json()["detail"]


async def test_a_change_with_no_check_rows_releases_vacuously(
        client, admin_auth, val, session_factory):
    """Legacy pin: nobody opened stage 9 on this change, so the guard has
    nothing to hold it to and behaves exactly as it did before this module."""
    from app.services.validation_service import ValidationService
    async with session_factory() as s:
        change = await s.get(ChangeRequest, val["change_id"])
        assert await ValidationService.release_blocker(s, change) is None
    res = await _release(client, admin_auth, val)
    assert res.status_code == 400, res.text
    assert "validation" not in res.json()["detail"]


# --- the loop back ----------------------------------------------------------

async def _escalate(client, auth, val, **body):
    return await client.post(
        f"/api/v1/changes/{val['change_id']}/transition", headers=auth,
        json={"to_status": "in_implementation", **body})


async def _summation(client, auth, val):
    res = await client.get(
        f"/api/v1/changes/{val['change_id']}/summation", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def test_escalation_back_needs_a_reason_and_logs_it(client, val):
    pm = await _auth(client, val, "Project Manager")
    res = await _escalate(client, pm, val)
    assert res.status_code == 400, res.text
    assert "A reason is required" in res.json()["detail"]

    res = await _escalate(client, pm, val,
                          reason="cycle time 4 s over — replan the timing and "
                                 "reopen the price")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "in_implementation"
    actions = await _actions(client, pm, val["change_id"])
    assert "validation_escalated" in actions


async def test_only_pm_sales_lead_or_admin_may_send_it_back(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    res = await _escalate(client, tool, val, reason="weight is off")
    assert res.status_code == 403, res.text

    sales = await _auth(client, val, "Sales")
    res = await _escalate(client, sales, val,
                          reason="weight is off, renegotiating")
    assert res.status_code == 200, res.text


# --- the actuals P&L --------------------------------------------------------

async def _book(client, auth, val, dept, hours):
    return await client.post(
        f"/api/v1/changes/{val['change_id']}/implementation/bookings",
        headers=auth,
        json={"department_id": val["dept"][dept], "hours": hours})


async def test_actuals_ride_on_the_summation_and_flag_unrated_hours(
        client, admin_auth, val):
    """Plan and actual are read together, so they are served together: the
    P&L card reads the summation and finds both halves in one payload."""
    assert (await _book(client, admin_auth, val, "Tool Engineer",
                        6.0)).status_code == 201
    assert (await _book(client, admin_auth, val, "Development",
                        2.0)).status_code == 201

    actuals = (await _summation(client, admin_auth, val))["actuals"]
    by_name = {d["department_name"]: d for d in actuals["departments"]}

    tool = by_name["Tool Engineer"]
    assert tool["booked_hours"] == 6.0 and tool["hourly_rate"] == 100.0
    assert tool["actual_cost"] == 600.0
    assert tool["unrated"] is False

    dev = by_name["Development"]
    assert dev["booked_hours"] == 2.0 and dev["hourly_rate"] is None
    # No rate at this plant: counted at zero and SAID so, never invented.
    assert dev["actual_cost"] == 0.0
    assert dev["unrated"] is True
    assert dev["plan_cost"] == 260.0            # its lifecycle cost line

    assert actuals["total_booked_hours"] == 8.0
    assert actuals["total_actual"] == 600.0
    assert actuals["unrated_hours"] is True
    # Tool Engineer's plan side is its €1000 costing position.
    assert actuals["total_plan"] == 1260.0
    assert actuals["variance"] == -660.0


async def test_actuals_extras_carry_the_scrap_quote_and_the_weight_delta(
        client, admin_auth, val, session_factory):
    tool = await _auth(client, val, "Tool Engineer")
    await _check(client, tool, val, "Tool Engineer", "weight", value=530.0)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, val["change_id"])
        change.bank_build_mode = "planned_scrap"
        change.scrap_quote_price = 4200.0
        await s.commit()

    actuals = (await _summation(client, admin_auth, val))["actuals"]
    extras = {e["key"]: e for e in actuals["extras"]}
    assert extras["scrap_quote"]["amount"] == 4200.0
    assert extras["weight_delta"]["delta_g"] == 30.0
    # The weight delta is a negotiation, not arithmetic this service does.
    assert extras["weight_delta"]["amount"] is None
    assert extras["weight_delta"]["acknowledged"] is False
    assert actuals["total_extras"] == 4200.0

    # The same block is served standalone for callers with no use for a grid.
    res = await client.get(
        f"/api/v1/pnl/changes/{val['change_id']}/actuals", headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["actuals"]["total_extras"] == 4200.0
