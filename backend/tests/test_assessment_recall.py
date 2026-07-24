"""A change in in_assessment can be recalled to scoping to fix a flawed
impacted set — but only while no assessment work has started. Recall tears
down the spawned assessments + routing so a corrected set rebuilds cleanly."""
import pytest

from tests.conftest import advance_to_assessment
from tests.test_changes import departments  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _in_assessment(client, auth, seed, session_factory, part):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "recall test",
        "change_type": "physical_part", "lead_id": seed["engineer_id"],
    }, headers=auth)
    cid = res.json()["id"]
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part["part_id"], "is_lead": True}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, cid)
    return cid


async def test_recall_tears_down_assessments(
        client, admin_auth, seed, departments, session_factory, part):
    cid = await _in_assessment(client, admin_auth, seed, session_factory, part)
    before = await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)
    assert len(before.json()["assessments"]) > 0

    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "scoping"

    after = await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)
    assert after.json()["assessments"] == []


async def test_recall_refused_after_assessment_submitted(
        client, admin_auth, seed, departments, session_factory, part):
    cid = await _in_assessment(client, admin_auth, seed, session_factory, part)
    a = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)
         ).json()["assessments"][0]
    await client.post(f"/api/v1/changes/{cid}/assessments",
                      json={"department_id": a["department_id"], "verdict": "feasible"},
                      headers=admin_auth)

    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "scoping"}, headers=admin_auth)
    assert blocked.status_code == 400, blocked.text
    assert "started" in blocked.json()["detail"].lower()


async def test_recall_then_resubmit_rebuilds_routing(
        client, admin_auth, seed, departments, session_factory, part):
    cid = await _in_assessment(client, admin_auth, seed, session_factory, part)
    await client.post(f"/api/v1/changes/{cid}/transition",
                      json={"to_status": "scoping"}, headers=admin_auth)
    # impact lock, deadline, and proceed meeting persist across recall — re-submit
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_assessment"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    after = await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)
    assert len(after.json()["assessments"]) > 0
