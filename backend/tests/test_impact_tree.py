import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _make_part(client, eng_auth, seed, number, name, parent_id=None,
                     part_type="internal_mfg"):
    body = {"project_id": seed["project_id"], "part_number": number,
            "name": name, "part_type": part_type,
            "data_classification": "confidential"}
    if parent_id is not None:
        body["parent_part_id"] = parent_id
    res = await client.post("/api/v1/parts", json=body, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    pid = res.json()["id"]
    res = await client.post(f"/api/v1/parts/{pid}/revisions/rfq",
                            json={"summary": "init"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    return {"part_id": pid, "revision_id": res.json()["id"]}


async def _make_change_with_lead(client, eng_auth, seed, lead_part_id):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "tree", "change_type": "tooling",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    change = res.json()
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": lead_part_id, "is_lead": True},
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    return change


async def test_impact_tree_marks_impacted_and_lead(client, eng_auth, seed):
    asm = await _make_part(client, eng_auth, seed, "ASM-1", "Assembly",
                           part_type="sub_assembly")
    child = await _make_part(client, eng_auth, seed, "CHD-1", "Child",
                             parent_id=asm["part_id"])
    change = await _make_change_with_lead(client, eng_auth, seed, child["part_id"])

    res = await client.get(f"/api/v1/changes/{change['id']}/impact-tree",
                           headers=eng_auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["lead_part_id"] == child["part_id"]
    roots = {n["part_id"]: n for n in data["tree"]}
    assert asm["part_id"] in roots
    child_node = next(c for c in roots[asm["part_id"]]["children"]
                      if c["part_id"] == child["part_id"])
    assert child_node["is_impacted"] is True and child_node["is_lead"] is True
    assert roots[asm["part_id"]]["is_impacted"] is False


async def test_suggest_rollups_walks_bom_parents_transitively(
        client, eng_auth, seed, session_factory):
    top = await _make_part(client, eng_auth, seed, "TOP-1", "Top",
                           part_type="sub_assembly")
    mid = await _make_part(client, eng_auth, seed, "MID-1", "Mid",
                           part_type="sub_assembly")
    leaf = await _make_part(client, eng_auth, seed, "LEAF-1", "Leaf")
    change = await _make_change_with_lead(client, eng_auth, seed, leaf["part_id"])

    from app.models.part import PartBOMItem
    async with session_factory() as s:
        s.add(PartBOMItem(revision_id=mid["revision_id"],
                          child_part_id=leaf["part_id"], name="leaf", quantity=1,
                          item_number="10", created_by=seed["engineer_id"]))
        s.add(PartBOMItem(revision_id=top["revision_id"],
                          child_part_id=mid["part_id"], name="mid", quantity=1,
                          item_number="10", created_by=seed["engineer_id"]))
        await s.commit()

    res = await client.post(
        f"/api/v1/changes/{change['id']}/impact-tree/suggest",
        json={"part_ids": [leaf["part_id"]]}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert set(res.json()["suggested_part_ids"]) == {top["part_id"], mid["part_id"]}


async def test_apply_selection_adds_and_removes(client, eng_auth, seed):
    lead = await _make_part(client, eng_auth, seed, "L-1", "Lead")
    extra = await _make_part(client, eng_auth, seed, "X-1", "Extra")
    change = await _make_change_with_lead(client, eng_auth, seed, lead["part_id"])

    res = await client.put(f"/api/v1/changes/{change['id']}/impacted-items",
                           json={"part_ids": [lead["part_id"], extra["part_id"]]},
                           headers=eng_auth)
    assert res.status_code == 200, res.text
    assert set(res.json()["impacted_part_ids"]) == {lead["part_id"], extra["part_id"]}

    # dropping the lead is refused
    res = await client.put(f"/api/v1/changes/{change['id']}/impacted-items",
                           json={"part_ids": [extra["part_id"]]}, headers=eng_auth)
    assert res.status_code == 400
    assert "lead" in res.json()["detail"].lower()

    # removing the extra is fine
    res = await client.put(f"/api/v1/changes/{change['id']}/impacted-items",
                           json={"part_ids": [lead["part_id"]]}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["impacted_part_ids"] == [lead["part_id"]]


async def test_apply_selection_locked_after_kickoff(client, eng_auth, seed,
                                                    session_factory):
    lead = await _make_part(client, eng_auth, seed, "L-2", "Lead2")
    extra = await _make_part(client, eng_auth, seed, "X-2", "Extra2")
    change = await _make_change_with_lead(client, eng_auth, seed, lead["part_id"])

    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, change["id"])
        c.status = "in_implementation"
        await s.commit()

    res = await client.put(f"/api/v1/changes/{change['id']}/impacted-items",
                           json={"part_ids": [lead["part_id"], extra["part_id"]]},
                           headers=eng_auth)
    assert res.status_code == 400
    assert "locked" in res.json()["detail"].lower()
