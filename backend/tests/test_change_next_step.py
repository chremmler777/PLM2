"""The cockpit's "missing before <next stage>" checklist (next_step on the
change detail) names exactly what the transition guards would refuse on."""
import pytest
from datetime import datetime
from sqlalchemy import update

from tests.conftest import satisfy_capture_gate, to_scoping, lock_impact

pytestmark = pytest.mark.asyncio


async def create_change(client, auth, project_id, **overrides):
    body = {"project_id": project_id, "title": "Next step",
            "change_type": "physical_part", **overrides}
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def next_step(client, auth, change_id):
    res = await client.get(f"/api/v1/changes/{change_id}", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["next_step"]


def keys(step):
    return [i["key"] for i in step["items"]]


async def test_captured_lists_the_kickoff_gaps(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"],
                                 customer_relevant=True)
    step = await next_step(client, admin_auth, change["id"])
    assert step["to"] == "scoping"
    assert keys(step) == ["description", "attachment", "quote_deadline", "lead"]
    assert {i["kind"] for i in step["items"]} == {"soft"}


async def test_captured_complete_has_nothing_missing(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    await satisfy_capture_gate(client, admin_auth, change["id"])
    step = await next_step(client, admin_auth, change["id"])
    assert step == {"to": "scoping", "items": []}


async def test_scoping_needs_meeting_and_impacted_set(client, admin_auth, seed, part):
    change = await create_change(client, admin_auth, seed["project_id"])
    await satisfy_capture_gate(client, admin_auth, change["id"])
    await to_scoping(client, admin_auth, change["id"])
    step = await next_step(client, admin_auth, change["id"])
    assert step["to"] == "in_assessment"
    assert keys(step)[:2] == ["meeting", "impacted_items"]

    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": part["part_id"], "is_lead": True},
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    assert "impact_confirmed" in keys(await next_step(client, admin_auth, change["id"]))


async def test_scoping_ready_once_meeting_open_and_impact_locked(
        client, admin_auth, seed, part, session_factory):
    from app.models.change import ChangeMeeting
    change = await create_change(client, admin_auth, seed["project_id"])
    await satisfy_capture_gate(client, admin_auth, change["id"])
    await to_scoping(client, admin_auth, change["id"])
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part["part_id"], "is_lead": True},
                      headers=admin_auth)
    await lock_impact(session_factory, change["id"])
    async with session_factory() as s:
        s.add(ChangeMeeting(
            change_id=change["id"], meeting_date=datetime.utcnow(),
            participants=[], notes=None, decision=None,
            selected_department_ids=[1], created_by=seed["admin_id"]))
        await s.commit()
    step = await next_step(client, admin_auth, change["id"])
    assert [i for i in step["items"] if i["kind"] == "hard"] == []


async def test_needs_info_asks_for_a_follow_up_meeting(
        client, admin_auth, seed, session_factory):
    from app.models.change import ChangeMeeting
    change = await create_change(client, admin_auth, seed["project_id"])
    await satisfy_capture_gate(client, admin_auth, change["id"])
    await to_scoping(client, admin_auth, change["id"])
    async with session_factory() as s:
        s.add(ChangeMeeting(
            change_id=change["id"], meeting_date=datetime.utcnow(),
            participants=[], notes=None, decision="needs_info",
            decision_reason="drawing", selected_department_ids=[1],
            created_by=seed["admin_id"]))
        await s.commit()
    assert keys(await next_step(client, admin_auth, change["id"]))[0] == "follow_up_meeting"


async def test_quoted_needs_acceptance_and_both_signoffs(
        client, admin_auth, seed, session_factory):
    from app.models.change import ChangeRequest
    change = await create_change(client, admin_auth, seed["project_id"],
                                 customer_relevant=True)
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == change["id"])
                        .values(status="quoted"))
        await s.commit()
    step = await next_step(client, admin_auth, change["id"])
    assert step["to"] == "approved"
    assert keys(step) == ["customer_accepted", "pm_signoff", "quality_signoff"]


async def test_approved_names_the_release_gate(client, admin_auth, seed, session_factory):
    from app.models.change import ChangeRequest
    change = await create_change(client, admin_auth, seed["project_id"])
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == change["id"])
                        .values(status="approved"))
        await s.commit()
    step = await next_step(client, admin_auth, change["id"])
    assert step["to"] == "in_implementation"
    assert {"key": "gate", "kind": "soft", "detail": "release"} in step["items"]
    assert {"key": "timing_validated", "kind": "soft"} in step["items"]


async def test_no_next_step_once_closed(client, admin_auth, seed, session_factory):
    from app.models.change import ChangeRequest
    change = await create_change(client, admin_auth, seed["project_id"])
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == change["id"])
                        .values(status="closed"))
        await s.commit()
    assert await next_step(client, admin_auth, change["id"]) is None
