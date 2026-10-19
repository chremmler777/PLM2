"""R24 (A1-03 follow-through): a read-only user named as lead gets no write
flag from stage-state, so the page offers no button the auth layer refuses
with 403 (cancel, hold, reject, impact edits, the meeting record)."""
import pytest

from app.auth.security import get_password_hash
from app.models.entities import User
from tests.conftest import login
from tests.test_ecr_solid_tasks import _as, _create, _set, team  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _viewer(session_factory, seed):
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="viewlead",
                 email="viewlead@test.io", full_name="View Lead",
                 hashed_password=get_password_hash("x-secret-123"),
                 role="viewer", is_active=True, mfa_enabled=False)
        s.add(u); await s.commit()
        return u.id


@pytest.mark.parametrize("status", ["scoping", "in_assessment", "quoted"])
async def test_viewer_lead_gets_no_write_flags(client, seed, team, session_factory, status):
    viewer = await _viewer(session_factory, seed)
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "viewer lead")
    await _set(session_factory, cid, status=status, lead_id=viewer)
    auth = await login(client, "viewlead@test.io", "x-secret-123", admin=False)
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=auth)).json()
    assert st["can_transition"] and not any(st["can_transition"].values()), st["can_transition"]
    assert st["can_edit_impact"] is False
    assert st["can_record_meeting"] is False
    assert st["can_approve_internal"] is False
    assert not (st.get("assessment") or {}).get("can_close")
    # the backend refuses what the flags hide
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "cancelled", "reason": "x"}, headers=auth)
    assert res.status_code == 403


async def test_pm_keeps_the_flags_a_viewer_lead_loses(client, seed, team, session_factory):
    """NEGATIVE of the above: a Project Management member on the same change
    still records the meeting and may cancel."""
    viewer = await _viewer(session_factory, seed)
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "viewer lead pm")
    await _set(session_factory, cid, status="scoping", lead_id=viewer)
    pm = await _as(client, "Project Manager")
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=pm)).json()
    assert st["can_record_meeting"] is True
    assert st["can_transition"].get("cancelled") is True
