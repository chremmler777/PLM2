import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_deviation_model_persists(session_factory, seed):
    from app.models.change import (
        ChangeRequest, ChangeTransitionDeviation, TRANSITION_DEVIATION_STATUSES,
    )
    async with session_factory() as s:
        change = ChangeRequest(
            change_number="CR-D-1", project_id=seed["project_id"], title="d",
            change_type="physical_part", status="captured",
            raised_by=seed["engineer_id"])
        s.add(change); await s.flush()
        s.add(ChangeTransitionDeviation(
            change_id=change.id, to_status="in_assessment",
            reason="PPT only at this stage", proposed_by=seed["engineer_id"]))
        await s.commit()
        dev = (await s.execute(select(ChangeTransitionDeviation))).scalar_one()
    assert dev.status == "pending"
    assert dev.to_status == "in_assessment"
    assert TRANSITION_DEVIATION_STATUSES == ("pending", "approved", "rejected", "consumed")


async def _change(client, auth, seed, **over):
    body = {"project_id": seed["project_id"], "title": "dev flow",
            "change_type": "physical_part", "lead_id": seed["engineer_id"]}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_propose_and_admin_approves(client, eng_auth, admin_auth, seed):
    c = await _change(client, eng_auth, seed)
    res = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "PPT only"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    dev = res.json()
    assert dev["status"] == "pending"

    # 4-eyes: proposer cannot decide their own deviation
    veto = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "approved"}, headers=eng_auth)
    assert veto.status_code == 400
    assert "own" in veto.json()["detail"].lower()

    ok = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "approved", "note": "ok for capture-stage"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"

    listed = await client.get(f"/api/v1/changes/{c['id']}/deviations", headers=eng_auth)
    assert listed.json()[0]["status"] == "approved"


async def test_reject_and_duplicate_pending_blocked(client, eng_auth, admin_auth, seed):
    c = await _change(client, eng_auth, seed)
    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r1"}, headers=eng_auth)).json()
    dup = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r2"}, headers=eng_auth)
    assert dup.status_code == 400
    rej = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "rejected", "note": "not enough info"}, headers=admin_auth)
    assert rej.json()["status"] == "rejected"
    # after rejection a new proposal is allowed again
    again = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r3"}, headers=eng_auth)
    assert again.status_code == 200
