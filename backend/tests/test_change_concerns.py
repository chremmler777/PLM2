"""Concerns: parallel team flags feeding the scoping decision."""
import pytest

pytestmark = pytest.mark.asyncio


async def _change_in_scoping(client, auth, seed, suffix):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": f"concern {suffix}",
        "change_type": "physical_part", "lead_id": seed["engineer_id"]}, headers=auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": f"ART-C{suffix}",
        "name": "Part", "part_type": "internal_mfg"}, headers=auth)
    assert part.status_code in (200, 201), part.text
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part.json()["id"], "is_lead": True}, headers=auth)
    # A required-by deadline is a scoping-exit gate; set it so these tests
    # exercise the concern rules rather than blocking on the deadline.
    await client.patch(f"/api/v1/changes/{cid}",
                       json={"required_by_date": "2026-12-31T12:00:00Z"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 200, res.text
    return cid


async def _dept_ids(session_factory):
    """Real department ids — the meeting validates them."""
    from sqlalchemy import select
    from app.models.workflow import Department
    from app.services.wf_seed_service import seed_assessment_standard
    async with session_factory() as s:
        await seed_assessment_standard(s)
        await s.commit()
    async with session_factory() as s:
        return [d for (d,) in await s.execute(select(Department.id).limit(1))]


async def _lock_impact(session_factory, cid):
    """Assessment is hard-gated on a locked impacted set; lock it directly so
    these tests reach the concern rules."""
    from datetime import datetime
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.impact_confirmed_at = datetime.utcnow()
        c.impact_confirmed_by = c.raised_by
        await s.commit()


async def _meeting(client, auth, cid, dept_ids):
    res = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": [{"name": "Eva"}],
        "selected_department_ids": dept_ids}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_concern_records_who_objects_and_why(client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "1")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "reject_proposal", "note": "Tool cannot hold the tolerance"})
    assert res.status_code == 200, res.text
    c = res.json()
    assert c["kind"] == "reject_proposal"
    assert c["note"] == "Tool cannot hold the tolerance"
    assert c["raised_by"] == seed["engineer_id"]
    assert c["raised_by_name"]           # the flag names its author
    assert c["is_open"] is True


async def test_concern_needs_a_note(client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "2")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "   "})
    assert res.status_code == 400, res.text


async def test_second_open_concern_of_a_kind_is_refused(client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "3")
    body = {"kind": "needs_info", "note": "Missing the CAD"}
    assert (await client.post(f"/api/v1/changes/{cid}/concerns", json=body,
                              headers=eng_auth)).status_code == 200
    res = await client.post(f"/api/v1/changes/{cid}/concerns", json=body, headers=eng_auth)
    assert res.status_code == 400, res.text
    assert "already have an open concern" in res.json()["detail"]


async def test_only_the_author_may_withdraw_even_for_an_admin(
        client, eng_auth, admin_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "4")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "reject_proposal", "note": "No capacity"})
    concern_id = res.json()["id"]

    # Clearing somebody else's objection is the thing this prevents — an admin
    # is not exempt.
    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}", headers=admin_auth)
    assert res.status_code == 400, res.text
    assert "only the person who raised" in res.json()["detail"].lower()

    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False
    # ...and not twice.
    assert (await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                                headers=eng_auth)).status_code == 400


async def test_open_concern_blocks_proceed_until_withdrawn(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "5")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "reject_proposal", "note": "Timing impossible"})
    concern_id = res.json()["id"]

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert "open concern" in detail
    assert "Timing" not in detail          # names the people, not the notes

    await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}", headers=eng_auth)
    await _lock_impact(session_factory, cid)
    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_negative_decision_resolves_the_open_concerns(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "6")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))
    await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                      json={"kind": "needs_info", "note": "Need the customer drawing"})

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide", headers=eng_auth,
                            json={"decision": "needs_info",
                                  "reason": "Customer drawing missing"})
    assert res.status_code == 200, res.text
    assert res.json()["decision_reason"] == "Customer drawing missing"

    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns", headers=eng_auth)).json()
    assert len(concerns) == 1
    assert concerns[0]["is_open"] is False
    assert concerns[0]["resolved_by_meeting_id"] == mid
    # The change stays in scoping — needs_info is not a rejection.
    got = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert got.json()["status"] == "scoping"


async def test_meeting_reject_requires_a_reason_and_carries_it_to_the_change(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "7")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "reject"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    assert "reason is required" in res.json()["detail"].lower()

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide", headers=eng_auth,
                            json={"decision": "reject", "reason": "Not economical at this volume"})
    assert res.status_code == 200, res.text
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["status"] == "rejected"
    # One decision, one justification — the meeting's reason is the change's.
    assert got["rejection_reason"] == "Not economical at this volume"


async def test_needs_info_requires_saying_what_is_missing(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "8")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))
    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "needs_info"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    assert "what information is missing" in res.json()["detail"].lower()


async def test_a_change_can_be_rejected_at_capture_without_being_scoped(
        client, eng_auth, seed, session_factory):
    """A request turned down outright never needed an impacted set — forcing it
    through scoping on the way out would demand work on a change that is dying."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "dead on arrival",
        "change_type": "physical_part", "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide", headers=eng_auth,
                            json={"decision": "reject", "reason": "Customer withdrew"})
    assert res.status_code == 200, res.text
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["status"] == "rejected"
    assert got["rejection_reason"] == "Customer withdrew"
