"""A risk raised from a checklist row remembers which row it came from."""
import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.workflow import Department

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ctx(session_factory, seed):
    async with session_factory() as s:
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        change = ChangeRequest(
            change_number="C-CK-1", title="ck", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id, department_id=dept.id, stage_order=1))
        await s.commit()
        return {"change_id": change.id, "department_id": dept.id}


async def _risk(client, auth, ctx, **over):
    body = {"kind": "risk", "note": "Cooling line clash", "risk_type": "timing",
            "severity": 2, "department_id": ctx["department_id"]}
    body.update(over)
    return await client.post(f"/api/v1/changes/{ctx['change_id']}/concerns",
                             json=body, headers=auth)


async def test_risk_keeps_its_checklist_key(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx, checklist_key="threed_change")
    assert res.status_code == 200, res.text
    assert res.json()["checklist_key"] == "threed_change"
    listed = await client.get(f"/api/v1/changes/{ctx['change_id']}/concerns",
                              headers=admin_auth)
    assert listed.json()[0]["checklist_key"] == "threed_change"


async def test_risk_without_key_still_works(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx)
    assert res.status_code == 200, res.text
    assert res.json()["checklist_key"] is None


async def test_unknown_key_is_refused(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx, checklist_key="pfmea_update")  # APQP-only
    assert res.status_code == 400
    assert "checklist" in res.json()["detail"].lower()


async def test_free_line_key_is_accepted(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx, checklist_key="free:Hot runner: zone 3")
    assert res.status_code == 200, res.text
    assert res.json()["checklist_key"] == "free:Hot runner: zone 3"


async def test_overlong_key_is_refused(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx, checklist_key="free:" + "x" * 200)
    assert res.status_code in (400, 422)


async def test_key_only_for_risks(session_factory, ctx, seed):
    from app.services.meeting_service import MeetingService
    from app.services.change_service import ChangeError
    from app.models.entities import User
    async with session_factory() as s:
        change = await s.get(ChangeRequest, ctx["change_id"])
        change.status = "scoping"
        await s.flush()
        await s.refresh(change, ["concerns"])
        user = await s.get(User, seed["admin_id"])
        with pytest.raises(ChangeError, match="checklist"):
            await MeetingService.raise_concern(
                s, change, user, "needs_info", "why?", checklist_key="threed_change")
