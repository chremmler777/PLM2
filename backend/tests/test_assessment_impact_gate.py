"""The impacted set must be LOCKED (R&D-confirmed) before a change may enter
assessment. Hard gate: no approved transition deviation can bypass it."""
import pytest

from tests.conftest import record_proceed_meeting
from tests.test_changes import departments  # noqa: F401 (reused fixture)

pytestmark = pytest.mark.asyncio


async def _scoping_ready(client, auth, seed, session_factory, part):
    """Create a change with one impacted item, in 'scoping' with a deadline and
    a recorded 'proceed' meeting — everything ready for assessment EXCEPT the
    impact lock."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "gate test",
        "change_type": "physical_part", "lead_id": seed["engineer_id"],
    }, headers=auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part["part_id"], "is_lead": True}, headers=auth)
    from tests.conftest import to_scoping
    await to_scoping(client, auth, cid)
    await record_proceed_meeting(session_factory, cid)
    return cid


async def test_assessment_blocked_until_impact_locked(
        client, admin_auth, seed, departments, session_factory, part):
    cid = await _scoping_ready(client, admin_auth, seed, session_factory, part)
    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_assessment"}, headers=admin_auth)
    assert blocked.status_code == 400, blocked.text
    assert "lock" in blocked.json()["detail"].lower()

    await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=admin_auth)
    ok = await client.post(f"/api/v1/changes/{cid}/transition",
                           json={"to_status": "in_assessment"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "in_assessment"


async def test_deviation_cannot_bypass_lock_gate(
        client, admin_auth, eng_auth, seed, departments, session_factory, part):
    cid = await _scoping_ready(client, eng_auth, seed, session_factory, part)
    dev = (await client.post(f"/api/v1/changes/{cid}/deviations", json={
        "to_status": "in_assessment", "reason": "skip lock"}, headers=eng_auth)).json()
    ok = await client.post(f"/api/v1/changes/{cid}/deviations/{dev['id']}/decide",
                           json={"decision": "approved"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text

    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400, blocked.text
    assert "lock" in blocked.json()["detail"].lower()


from tests.test_impact_confirmation import rd_member_auth  # noqa: F401,E402


async def test_scoping_surfaces_lock_action_for_rd(
        client, admin_auth, rd_member_auth, seed, session_factory, part):
    cid = await _scoping_ready(client, admin_auth, seed, session_factory, part)
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                             headers=rd_member_auth["auth"])).json()["actions"]
    assert any(a["kind"] == "impact_confirm" for a in acts), acts

    # once locked, the action is gone
    await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                      headers=rd_member_auth["auth"])
    acts2 = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                              headers=rd_member_auth["auth"])).json()["actions"]
    assert not any(a["kind"] == "impact_confirm" for a in acts2), acts2
