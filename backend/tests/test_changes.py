# backend/tests/test_changes.py
import pytest

pytestmark = pytest.mark.asyncio


async def _create_change(client, auth, project_id, **over):
    body = {"project_id": project_id, "title": "Wall thickness +0.2mm",
            "change_type": "physical_part", "reason": "Sink marks on Class-A surface"}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_create_change_assigns_number_and_captured_status(client, eng_auth, seed):
    data = await _create_change(client, eng_auth, seed["project_id"])
    assert data["status"] == "captured"
    assert data["change_number"].startswith("CR-")
    assert data["change_type"] == "physical_part"


async def test_list_and_get_change(client, eng_auth, seed):
    created = await _create_change(client, eng_auth, seed["project_id"])
    res = await client.get(f"/api/v1/changes?project_id={seed['project_id']}", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert any(c["id"] == created["id"] for c in res.json())

    res = await client.get(f"/api/v1/changes/{created['id']}", headers=eng_auth)
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["id"] == created["id"]
    assert detail["impacted_items"] == []


async def _transition(client, auth, change_id, to_status, **over):
    body = {"to_status": to_status}
    body.update(over)
    return await client.post(f"/api/v1/changes/{change_id}/transition", json=body, headers=auth)


async def test_transition_requires_impacted_item_then_forced_override(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    # Soft guard blocks without impacted items + no justification
    res = await _transition(client, eng_auth, change["id"], "in_assessment")
    assert res.status_code == 400, res.text
    # Forced override with justification succeeds and logs it
    res = await _transition(client, eng_auth, change["id"], "in_assessment",
                            justification="PPT only at this stage")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "in_assessment"


async def test_illegal_transition_rejected(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    res = await _transition(client, eng_auth, change["id"], "released")
    assert res.status_code == 400, res.text


async def test_cancel_requires_reason(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    res = await _transition(client, eng_auth, change["id"], "cancelled")
    assert res.status_code == 400, res.text
    res = await _transition(client, eng_auth, change["id"], "cancelled",
                            cancellation_reason="Customer withdrew RFQ")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"
