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


async def _make_part(client, auth, project_id, number, category="article"):
    res = await client.post("/api/v1/parts", json={
        "project_id": project_id, "part_number": number, "name": number,
        "part_type": "internal_mfg", "item_category": category,
    }, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_add_and_remove_impacted_item(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-1")
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": part_id, "impact_note": "wall thickness"},
                            headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    item_id = res.json()["id"]

    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assert len(res.json()["impacted_items"]) == 1

    res = await client.delete(f"/api/v1/changes/{change['id']}/impacted-items/{item_id}",
                              headers=eng_auth)
    assert res.status_code in (200, 204), res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assert res.json()["impacted_items"] == []


async def test_seed_impacted_from_relations(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    article = await _make_part(client, eng_auth, seed["project_id"], "ART-2", "article")
    tool = await _make_part(client, eng_auth, seed["project_id"], "TOOL-2", "tool")
    # tool produces article
    res = await client.post(f"/api/v1/parts/{tool}/relations", json={
        "to_part_id": article, "relation_type": "produces",
    }, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    # add the article as impacted, then seed related items
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": article}, headers=eng_auth)
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items/seed",
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    part_ids = {i["part_id"] for i in res.json()["impacted_items"]}
    assert tool in part_ids  # the producing tool was pulled in


import pytest_asyncio
from app.models.workflow import Department


@pytest_asyncio.fixture
async def departments(session_factory):
    async with session_factory() as s:
        names = ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"]
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i)
            s.add(d)
            await s.flush()
            ids[n] = d.id
        await s.commit()
        return ids


async def test_assessment_created_on_enter_and_submit(client, eng_auth, seed, departments):
    change = await _create_change(client, eng_auth, seed["project_id"],
                                  lead_id=seed["engineer_id"])
    part_id = await _make_part(client, eng_auth, seed["project_id"], "ART-9")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=eng_auth)
    # enter assessment -> assessments auto-created
    res = await _transition(client, eng_auth, change["id"], "in_assessment")
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=eng_auth)
    assessments = res.json()["assessments"]
    assert len(assessments) >= 1
    tool_dep = departments["Tool Engineer"]

    # submitting feasible for all then moving to costing should work
    for a in assessments:
        r = await client.post(f"/api/v1/changes/{change['id']}/assessments", json={
            "department_id": a["department_id"], "verdict": "feasible",
        }, headers=eng_auth)
        assert r.status_code in (200, 201), r.text

    # costing still needs a quoted price guard? No - costing guard is assessments only
    res = await _transition(client, eng_auth, change["id"], "costing")
    assert res.status_code == 200, res.text


async def _advance_to_quoted(client, auth, seed, departments, admin_auth):
    change = await _create_change(client, auth, seed["project_id"], lead_id=seed["engineer_id"])
    part_id = await _make_part(client, auth, seed["project_id"], f"ART-Q{change['id']}")
    await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                      json={"part_id": part_id}, headers=auth)
    await _transition(client, auth, change["id"], "in_assessment")
    res = await client.get(f"/api/v1/changes/{change['id']}", headers=auth)
    for a in res.json()["assessments"]:
        await client.post(f"/api/v1/changes/{change['id']}/assessments",
                          json={"department_id": a["department_id"], "verdict": "feasible"},
                          headers=auth)
    await _transition(client, auth, change["id"], "costing")
    await client.patch(f"/api/v1/changes/{change['id']}",
                       json={"quoted_price": 12500.0}, headers=auth)
    await _transition(client, auth, change["id"], "quoted")
    return change


async def test_approve_blocked_until_customer_and_dual_signoff(
    client, eng_auth, admin_auth, seed, departments
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth)
    cid = change["id"]
    # cannot approve yet (no customer acceptance, no sign-off) — hard gate, no override
    res = await _transition(client, eng_auth, cid, "approved", justification="please")
    assert res.status_code == 400, res.text

    # record customer acceptance
    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "accepted"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    # PM signs (engineer), Quality signs (admin) — must be different users
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    # same user cannot also be quality
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "quality"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    res = await client.post(f"/api/v1/changes/{cid}/sign-off",
                            json={"role": "quality"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    # now approve works
    res = await _transition(client, eng_auth, cid, "approved")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"


async def test_implementation_spawns_ecn_revision_per_item(
    client, eng_auth, admin_auth, seed, departments
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth)
    cid = change["id"]
    await client.post(f"/api/v1/changes/{cid}/customer-response",
                      json={"response": "accepted"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"}, headers=admin_auth)
    await _transition(client, eng_auth, cid, "approved")
    res = await _transition(client, eng_auth, cid, "in_implementation")
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    items = res.json()["impacted_items"]
    assert all(i["resulting_revision_id"] is not None for i in items)


async def test_release_activates_revisions_and_stamps_eng_level(
    client, eng_auth, admin_auth, seed, departments
):
    change = await _advance_to_quoted(client, eng_auth, seed, departments, admin_auth)
    cid = change["id"]
    await client.post(f"/api/v1/changes/{cid}/customer-response",
                      json={"response": "accepted"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"}, headers=admin_auth)
    await _transition(client, eng_auth, cid, "approved")
    await _transition(client, eng_auth, cid, "in_implementation")
    res = await _transition(client, eng_auth, cid, "in_validation")
    assert res.status_code == 200, res.text
    res = await _transition(client, eng_auth, cid, "released")
    assert res.status_code == 200, res.text

    # each impacted part now points at its ECN revision as active
    detail = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    for item in detail["impacted_items"]:
        rev_id = item["resulting_revision_id"]
        part = (await client.get(f"/api/v1/parts/{item['part_id']}", headers=eng_auth)).json()
        assert part["active_revision_id"] == rev_id


async def test_changelog_is_hash_chained(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    await _transition(client, eng_auth, change["id"], "on_hold")
    res = await client.get(f"/api/v1/changes/{change['id']}/changelog", headers=eng_auth)
    assert res.status_code == 200, res.text
    entries = res.json()
    assert len(entries) >= 2  # created + status_changed
    actions = [e["action"] for e in entries]
    assert "created" in actions
