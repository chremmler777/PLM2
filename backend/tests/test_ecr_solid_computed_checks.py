"""ECR-solid §10 computed checks (lane L7, switch RELEASE_V2).

Weight, cycle time (Tool Engineer) and dimensions (APQP) are computed from a
measurement: sample size n, min and max, the measuring report or device id
(cycle time: plus the lot). PASS only if both min and max lie inside the
limits; the limits are fixed by the first measurement and never moved by a
retest. A retest adds a row, keeps the failed one, and says what changed
since (parameter / tool / material / method + ref).
"""
import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.change_validation import ValidationCheck, ValidationMeasurement
from app.services import cm_switches
from tests.test_validation_checks import _auth, _set_status, _state, _url, val  # noqa: F401

pytestmark = pytest.mark.asyncio

SPEC = {"lower_limit": 495.0, "upper_limit": 515.0,
        "spec_source": "drawing 886.197 D, weight 505 g +/-10"}


def _m(lo, hi, n=5, **extra):
    return {"sample_size": n, "min_value": lo, "max_value": hi,
            "measuring_ref": "scale WG-0042, report MR-2026-118", **extra}


async def _measure(client, auth, val, key, measurement, dept="Tool Engineer", **kw):
    return await client.post(_url(val, "/checks"), headers=auth, json={
        "department_id": val["dept"][dept], "check_key": key,
        "measurement": measurement, **kw})


def _row(state, key, dept="Tool Engineer"):
    return next(c for d in state["departments"] if d["department_name"] == dept
                for c in d["checks"] if c["check_key"] == key)


async def test_weight_in_tolerance_passes_and_stamps_the_midpoint(client, val, session_factory):
    tool = await _auth(client, val, "Tool Engineer")
    res = await _measure(client, tool, val, "weight", _m(503.0, 509.0, **SPEC))
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "passed"
    assert res.json()["value"] == 506.0
    row = _row(await _state(client, tool, val), "weight")
    assert row["computed"] is True
    assert (row["lower_limit"], row["upper_limit"]) == (495.0, 515.0)
    assert row["spec_source"].startswith("drawing 886.197")
    assert [m["result"] for m in row["measurements"]] == ["passed"]
    assert row["measurements"][0]["sample_size"] == 5
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, val["change_id"])).validated_part_weight_g == 506.0


async def test_one_value_outside_fails_whatever_the_client_says(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    # max above the upper limit: FAIL, even with status 'passed' posted
    res = await _measure(client, tool, val, "weight", _m(503.0, 516.2, **SPEC),
                         status="passed")
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "failed"
    row = _row(await _state(client, tool, val), "weight")
    assert row["status"] == "failed"
    assert "516.2" in row["measurements"][0]["line"]


async def test_negative_a_computed_check_is_not_ticked(client, val):
    """NEGATIVE: a plain pass with a value, or a measurement without its
    evidence, limits or a usable reference, is refused."""
    tool = await _auth(client, val, "Tool Engineer")
    res = await client.post(_url(val, "/checks"), headers=tool, json={
        "department_id": val["dept"]["Tool Engineer"], "check_key": "weight",
        "status": "passed", "value": 505.0})
    assert res.status_code == 400, res.text
    assert "sample size n, min and max" in res.json()["detail"]
    # first measurement without limits
    res = await _measure(client, tool, val, "weight", _m(503.0, 509.0))
    assert res.status_code == 400 and "limits" in res.json()["detail"]
    # 'ok' is no measuring report
    res = await _measure(client, tool, val, "weight",
                         {**_m(503.0, 509.0, **SPEC), "measuring_ref": "ok"})
    assert res.status_code == 400 and "measuring report" in res.json()["detail"]
    # min above max, n below 1
    res = await _measure(client, tool, val, "weight", _m(510.0, 503.0, **SPEC))
    assert res.status_code == 400 and "min" in res.json()["detail"]
    res = await _measure(client, tool, val, "weight", _m(503.0, 509.0, n=0, **SPEC))
    assert res.status_code == 400 and "sample size" in res.json()["detail"]


async def test_cycle_time_names_its_lot(client, val):
    tool = await _auth(client, val, "Tool Engineer")
    spec = {"lower_limit": 38.0, "upper_limit": 42.0,
            "spec_source": "process sheet PS-114 rev B, 40 s +/-2"}
    res = await _measure(client, tool, val, "cycle_time", _m(39.6, 41.1, n=30, **spec))
    assert res.status_code == 400, res.text
    assert "lot" in res.json()["detail"].lower()
    res = await _measure(client, tool, val, "cycle_time",
                         _m(39.6, 41.1, n=30, lot_ref="lot 2026-41-117", **spec))
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "passed"


async def test_retest_keeps_the_failed_row_and_says_what_changed(client, val, admin_auth):
    tool = await _auth(client, val, "Tool Engineer")
    pm = await _auth(client, val, "Project Manager")
    assert (await _measure(client, tool, val, "weight",
                           _m(512.0, 518.0, **SPEC))).json()["status"] == "failed"
    # NEGATIVE: a retest without what changed since
    res = await _measure(client, tool, val, "weight", _m(503.0, 509.0))
    assert res.status_code == 400, res.text
    assert "What changed since the failure" in res.json()["detail"]
    # NEGATIVE: a retest never moves the limits
    res = await _measure(client, tool, val, "weight", _m(
        503.0, 509.0, lower_limit=490.0, upper_limit=520.0, spec_source="wider",
        what_changed_kind="parameter", what_changed_ref="holding pressure -5 bar, PS-114 C"))
    assert res.status_code == 400, res.text
    assert "fixed" in res.json()["detail"]
    # NEGATIVE: no PM or admin retest (HARD #3)
    for auth in (pm, admin_auth):
        res = await _measure(client, auth, val, "weight", _m(
            503.0, 509.0, what_changed_kind="parameter",
            what_changed_ref="holding pressure -5 bar, PS-114 C"))
        assert res.status_code == 400 and "own department" in res.json()["detail"]
    # NEGATIVE: an unknown kind
    res = await _measure(client, tool, val, "weight", _m(
        503.0, 509.0, what_changed_kind="luck", what_changed_ref="tried again 2x"))
    assert res.status_code == 400, res.text
    res = await _measure(client, tool, val, "weight", _m(
        503.0, 509.0, what_changed_kind="parameter",
        what_changed_ref="holding pressure -5 bar, PS-114 C"))
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "passed"
    row = _row(await _state(client, tool, val), "weight")
    assert [m["result"] for m in row["measurements"]] == ["failed", "passed"]
    assert row["measurements"][1]["what_changed_kind"] == "parameter"


async def test_dimensions_are_apqps_computed_check(client, val, session_factory):
    """APQP's 'Parts measured' is computed too (worst deviation from nominal,
    mm); a member of another department may not enter it (NEGATIVE)."""
    from app.auth.security import get_password_hash
    from app.models.change_cost import CostingPosition
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    from tests.conftest import ENGINEER_PASSWORD, login
    async with session_factory() as s:
        d = Department(name="APQP", flow_type="action", is_active=True)
        s.add(d)
        await s.flush()
        u = User(organization_id=(await s.get(User, val["user"]["Tool Engineer"]["id"])).organization_id,
                 username="apqp", email="apqp@val.test", full_name="APQP",
                 role="engineer", hashed_password=get_password_hash(ENGINEER_PASSWORD),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=d.id))
        s.add(CostingPosition(change_id=val["change_id"], department_id=d.id,
                              label="Measuring", kind="internal", pricing="estimate",
                              est_cost=200.0, created_by=u.id))
        await s.commit()
        apqp_id = d.id
    val["dept"]["APQP"] = apqp_id
    apqp = await login(client, "apqp@val.test", ENGINEER_PASSWORD)
    tool = await _auth(client, val, "Tool Engineer")
    spec = {"lower_limit": -0.2, "upper_limit": 0.2,
            "spec_source": "drawing 886.197 D, general tolerance ISO 2768-m"}
    res = await _measure(client, tool, val, "measured", _m(-0.05, 0.12, n=3, **spec),
                         dept="APQP")
    assert res.status_code == 403, res.text
    res = await _measure(client, apqp, val, "measured", _m(-0.05, 0.12, n=3, **spec),
                         dept="APQP")
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "passed"
    row = _row(await _state(client, apqp, val), "measured", dept="APQP")
    assert row["computed"] is True and row["unit_short"] == "mm"


async def test_switch_off_keeps_the_plain_tick(client, val, monkeypatch):
    """RELEASE_V2 off: weight is ticked with its value as before."""
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    tool = await _auth(client, val, "Tool Engineer")
    res = await client.post(_url(val, "/checks"), headers=tool, json={
        "department_id": val["dept"]["Tool Engineer"], "check_key": "weight",
        "status": "passed", "value": 505.0})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "passed"
