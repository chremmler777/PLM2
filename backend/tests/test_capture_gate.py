"""Capture phase is Sales' hand-off: only starter departments may raise a
change, kickoff needs a complete capture (description + attachment + quote
deadline for customer-relevant changes), and meetings belong to scoping."""
from datetime import datetime, timedelta

import pytest

from tests.conftest import satisfy_capture_gate, make_internal

pytestmark = pytest.mark.asyncio


async def _create(client, auth, seed, **over):
    body = {"project_id": seed["project_id"], "title": "Capture gate",
            "reason": "r", "change_type": "physical_part"}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _kickoff(client, auth, cid):
    return await client.post(f"/api/v1/changes/{cid}/transition",
                             json={"to_status": "scoping"}, headers=auth)


async def _attach(client, auth, cid):
    res = await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": ("evidence.txt", b"x", "text/plain")}, headers=auth)
    assert res.status_code in (200, 201), res.text


async def test_kickoff_blocked_without_description(client, eng_auth, seed):
    change = await _create(client, eng_auth, seed, description=None)
    await _attach(client, eng_auth, change["id"])
    res = await _kickoff(client, eng_auth, change["id"])
    assert res.status_code == 400
    assert "description" in res.json()["detail"].lower()


async def test_kickoff_blocked_without_attachment(client, eng_auth, seed):
    change = await _create(client, eng_auth, seed, description="what changes")
    res = await _kickoff(client, eng_auth, change["id"])
    assert res.status_code == 400
    assert "attachment" in res.json()["detail"].lower()


async def test_kickoff_blocked_without_date_when_customer_relevant(
        client, eng_auth, seed):
    change = await _create(client, eng_auth, seed, description="what changes",
                           customer_relevant=True)
    await _attach(client, eng_auth, change["id"])
    res = await _kickoff(client, eng_auth, change["id"])
    assert res.status_code == 400
    assert "required-by date" in res.json()["detail"].lower()


async def test_internal_change_needs_no_date(client, eng_auth, seed):
    change = await _create(client, eng_auth, seed, description="what changes")
    await make_internal(client, eng_auth, change["id"])
    await _attach(client, eng_auth, change["id"])
    res = await _kickoff(client, eng_auth, change["id"])
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "scoping"


async def test_kickoff_passes_with_all_three(client, eng_auth, seed):
    change = await _create(client, eng_auth, seed, customer_relevant=True)
    await satisfy_capture_gate(client, eng_auth, change["id"])
    res = await _kickoff(client, eng_auth, change["id"])
    assert res.status_code == 200, res.text


async def test_kickoff_no_longer_requires_impacted_items(client, eng_auth, seed):
    """Impact moves to scoping — an empty impacted set no longer blocks."""
    change = await _create(client, eng_auth, seed)
    await satisfy_capture_gate(client, eng_auth, change["id"])
    res = await _kickoff(client, eng_auth, change["id"])
    assert res.status_code == 200, res.text


async def test_meeting_cannot_be_recorded_at_capture(client, eng_auth, seed):
    change = await _create(client, eng_auth, seed)
    res = await client.post(f"/api/v1/changes/{change['id']}/meetings",
                            json={"notes": "too early"}, headers=eng_auth)
    assert res.status_code == 400
    assert "scoping" in res.json()["detail"].lower()


async def _make_sales(session_factory, *, member_id: int | None = None) -> int:
    """A department flagged can_start_change, optionally with a member."""
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        dept = Department(name="Sales", flow_type="action", is_active=True,
                          can_start_change=True)
        s.add(dept)
        await s.flush()
        if member_id is not None:
            s.add(UserDepartment(user_id=member_id, department_id=dept.id))
        await s.commit()
        return dept.id


async def test_create_change_refused_without_starter_membership(
        client, eng_auth, seed, session_factory):
    """Once a starter department exists, a non-admin outside it is refused."""
    await _make_sales(session_factory)
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Nope", "reason": "r",
        "change_type": "physical_part"}, headers=eng_auth)
    assert res.status_code == 403
    assert "start" in res.json()["detail"].lower()


async def test_starter_department_member_can_create(client, eng_auth, seed,
                                                    session_factory):
    await _make_sales(session_factory, member_id=seed["engineer_id"])
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Sales raised", "reason": "r",
        "change_type": "physical_part"}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_capture_open_while_no_department_is_flagged(client, eng_auth, seed):
    """Nothing flagged anywhere -> the entry point stays open."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "Unconfigured", "reason": "r",
        "change_type": "physical_part"}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_internal_change_creation_is_refused(client, eng_auth, seed):
    """External flow only for now: the endpoint refuses to create an internal
    change, while the service keeps the capability."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "internal", "reason": "r",
        "change_type": "physical_part", "customer_relevant": False}, headers=eng_auth)
    assert res.status_code == 400
    assert "not enabled yet" in res.json()["detail"]
    assert "external" in res.json()["detail"]


async def test_customer_relevant_change_is_still_accepted(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "external", "reason": "r",
        "change_type": "physical_part", "customer_relevant": True}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["customer_relevant"] is True
