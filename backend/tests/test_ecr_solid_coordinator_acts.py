"""R18/R25/R37: the coordinator of a department with no member here (A5) is
a lead who can act (A1-05: active, not an admin account, with an active PLM
department), else Project Management; and with Quality unstaffed the limits
of a check are confirmed by the lead or a Project Management member, never
by whoever set them (A5-02), so a PASS can always count."""
import pytest

from app.auth.security import get_password_hash
from app.models.change import ChangeRequest
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from tests.conftest import ENGINEER_PASSWORD
from tests.test_ecr_solid_closeout_a5 import SPEC, _memberless, _weight_row
from tests.test_ecr_solid_fix_concession import _who, fix  # noqa: F401
from tests.test_validation_checks import _auth, _url, val  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _user(session_factory, fix, key, *, role="engineer", dept=None):
    async with session_factory() as s:
        org = (await s.get(User, fix["user"]["Tool Engineer"]["id"])).organization_id
        email = f"{key}@coord.test"
        u = User(organization_id=org, username=key, email=email, full_name=key.title(),
                 role=role, hashed_password=get_password_hash(ENGINEER_PASSWORD),
                 is_active=True, mfa_enabled=False)
        s.add(u); await s.flush()
        if dept is not None:
            s.add(UserDepartment(user_id=u.id, department_id=dept))
        await s.commit()
        return u.id, email


async def _set_lead(session_factory, fix, user_id):
    async with session_factory() as s:
        (await s.get(ChangeRequest, fix["change_id"])).lead_id = user_id
        await s.commit()


async def _measure(client, fix, auth, dept="Tool Engineer"):
    res = await client.post(_url(fix, "/checks"), headers=auth, json={
        "department_id": fix["dept"][dept], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 505.0, "max_value": 512.0,
                        "measuring_ref": "scale WG-0042, report MR-2026-118", **SPEC}})
    assert res.status_code == 201, res.text
    return res.json()


# --- the coordinator is a lead who can act ---------------------------------

async def test_viewer_lead_does_not_coordinate_pm_does(client, fix, session_factory):
    viewer, _ = await _user(session_factory, fix, "viewlead", role="viewer")
    await _set_lead(session_factory, fix, viewer)
    await _memberless(session_factory, fix, "Development", lead="Development")
    await _set_lead(session_factory, fix, viewer)
    from app.services.change_people import coordinates, coordinator
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        assert await coordinator(s, c) == (None, "Project Management")
        pm = await s.get(User, fix["user"]["Project Manager"]["id"])
        assert await coordinates(s, c, pm) is True
        # NEGATIVE: the viewer lead coordinates nothing
        assert await coordinates(s, c, await s.get(User, viewer)) is False
    pm_auth = await _auth(client, fix, "Project Manager")
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=pm_auth)).json()
            if t["change_id"] == fix["change_id"] and t["kind"] == "validation_check"
            and t.get("department_id") == fix["dept"]["Development"]]
    assert rows and "Project Management coordinates" in rows[0]["reason"]
    assert "Viewlead" not in rows[0]["reason"]


async def test_lead_with_only_retired_departments_does_not_coordinate(
        client, fix, session_factory):
    async with session_factory() as s:
        old = Department(name="Retired Dept", flow_type="action", is_active=False)
        s.add(old); await s.flush()
        retired_id = old.id
        await s.commit()
    lead, _ = await _user(session_factory, fix, "retiredlead", dept=retired_id)
    await _set_lead(session_factory, fix, lead)
    from app.services.change_people import coordinates, coordinator
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        assert await coordinator(s, c) == (None, "Project Management")
        assert await coordinates(s, c, await s.get(User, lead)) is False
    # an engineer lead with an active department still coordinates
    await _set_lead(session_factory, fix, fix["user"]["Development"]["id"])
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        assert (await coordinator(s, c))[0] == fix["user"]["Development"]["id"]


# --- limits with Quality unstaffed ----------------------------------------

async def test_viewer_lead_and_no_quality_pm_confirms_the_limits(
        client, fix, session_factory):
    viewer, _ = await _user(session_factory, fix, "viewlead2", role="viewer")
    await _memberless(session_factory, fix, "Quality", lead="Development")
    await _set_lead(session_factory, fix, viewer)
    tool = await _auth(client, fix, "Tool Engineer")
    await _measure(client, fix, tool)
    pm = await _auth(client, fix, "Project Manager")
    _, chk = await _weight_row(client, fix, pm)
    assert chk["limits_pending"] is True and chk["can_confirm_limits"] is True
    res = await client.post(_url(fix, f"/checks/{chk['check_id']}/limits"),
                            headers=pm, json={})
    assert res.status_code == 200 and res.json()["status"] == "passed", res.text


async def test_no_quality_the_lead_measures_pm_confirms(client, fix, session_factory):
    """A5-02 with Quality unstaffed: the lead measured for a member-less
    department; the lead is refused (own limits) and told who confirms; a
    Project Management member confirms and the PASS counts."""
    await _memberless(session_factory, fix, "Quality", "Tool Engineer", lead="Development")
    dev = await _auth(client, fix, "Development")
    await _measure(client, fix, dev)
    _, chk = await _weight_row(client, fix, dev)
    url = _url(fix, f"/checks/{chk['check_id']}/limits")
    assert chk["can_confirm_limits"] is False
    res = await client.post(url, headers=dev, json={})
    assert res.status_code == 403
    assert "Project Manager" in res.json()["detail"]          # names who confirms
    pm = await _auth(client, fix, "Project Manager")
    tasks = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=pm)).json()
             if t["change_id"] == fix["change_id"] and t["kind"] == "validation_check"
             and "Confirm the limits of" in (t.get("reason") or "")]
    assert tasks and tasks[0]["needs_you"]
    _, chk = await _weight_row(client, fix, pm)
    assert chk["can_confirm_limits"] is True
    res = await client.post(url, headers=pm, json={})
    assert res.status_code == 200 and res.json()["status"] == "passed", res.text
    _, chk = await _weight_row(client, fix, pm)
    assert chk["limits_pending"] is False


async def test_no_quality_a_staffed_department_member_still_cannot_confirm(
        client, fix, session_factory):
    """NEGATIVE: with Quality unstaffed, a member of another department is
    no confirmer (only the lead or Project Management)."""
    await _memberless(session_factory, fix, "Quality", lead="Project Manager")
    tool = await _auth(client, fix, "Tool Engineer")
    await _measure(client, fix, tool)
    proc = await _who(client, fix, "Process Engineer")
    _, chk = await _weight_row(client, fix, proc)
    res = await client.post(_url(fix, f"/checks/{chk['check_id']}/limits"),
                            headers=proc, json={})
    assert res.status_code == 403
    assert "Project Manager" in res.json()["detail"]


async def test_retired_quality_counts_as_unstaffed(client, fix, session_factory):
    """A retired Quality department grants nothing: the lead or Project
    Management confirm, its former member does not."""
    async with session_factory() as s:
        (await s.get(Department, fix["dept"]["Quality"])).is_active = False
        (await s.get(ChangeRequest, fix["change_id"])).lead_id = \
            fix["user"]["Development"]["id"]
        await s.commit()
    from app.services.validation_service import ValidationService
    async with session_factory() as s:
        c = await s.get(ChangeRequest, fix["change_id"])
        staffed, ids = await ValidationService.limits_confirmers(s, c)
    assert staffed is False
    assert ids == {fix["user"]["Development"]["id"], fix["user"]["Project Manager"]["id"]}
