"""Revision-scoped BOM tests."""
from tests.conftest import freeze_revision


async def _make_child_part(client, eng_auth, seed, part_number="P-300", name="Bolt"):
    res = await client.post(
        "/api/v1/parts",
        json={
            "project_id": seed["project_id"],
            "part_number": part_number,
            "name": name,
            "part_type": "purchased",
            "data_classification": "confidential",
        },
        headers=eng_auth,
    )
    return res.json()["id"]


async def test_bom_crud(client, eng_auth, part, seed):
    pid, rid = part["part_id"], part["revision_id"]
    child_id = await _make_child_part(client, eng_auth, seed)

    # Add item referencing a project part
    res = await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/bom",
        json={"child_part_id": child_id, "quantity": 4, "unit": "pcs"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    item = res.json()
    assert item["name"] == "Bolt"
    assert item["item_number"] == "10"
    assert item["child_part_number"] == "P-300"

    # Add free-text item: positions advance in steps of 10
    res = await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/bom",
        json={"name": "Adhesive", "quantity": 0.5, "unit": "m"},
        headers=eng_auth,
    )
    assert res.json()["item_number"] == "20"
    free_item_id = res.json()["id"]

    # List
    res = await client.get(f"/api/v1/parts/revisions/{rid}/bom", headers=eng_auth)
    assert [i["item_number"] for i in res.json()] == ["10", "20"]

    # Update quantity
    res = await client.put(
        f"/api/v1/parts/bom-items/{item['id']}", json={"quantity": 6}, headers=eng_auth
    )
    assert res.status_code == 200
    assert res.json()["quantity"] == 6

    # Delete
    res = await client.delete(f"/api/v1/parts/bom-items/{free_item_id}", headers=eng_auth)
    assert res.status_code == 200
    res = await client.get(f"/api/v1/parts/revisions/{rid}/bom", headers=eng_auth)
    assert len(res.json()) == 1


async def test_bom_rejects_self_reference(client, eng_auth, part):
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/bom",
        json={"child_part_id": part["part_id"]},
        headers=eng_auth,
    )
    assert res.status_code == 400


async def test_bom_requires_some_reference(client, eng_auth, part):
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/bom",
        json={"quantity": 1},
        headers=eng_auth,
    )
    assert res.status_code == 400


async def test_frozen_revision_bom_read_only(client, eng_auth, part, seed, session_factory):
    pid, rid = part["part_id"], part["revision_id"]
    child_id = await _make_child_part(client, eng_auth, seed, "P-301", "Nut")

    res = await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/bom",
        json={"child_part_id": child_id},
        headers=eng_auth,
    )
    item_id = res.json()["id"]

    await freeze_revision(session_factory, rid)

    res = await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/bom", json={"name": "Late"}, headers=eng_auth
    )
    assert res.status_code == 409
    res = await client.put(
        f"/api/v1/parts/bom-items/{item_id}", json={"quantity": 9}, headers=eng_auth
    )
    assert res.status_code == 409
    res = await client.delete(f"/api/v1/parts/bom-items/{item_id}", headers=eng_auth)
    assert res.status_code == 409

    # Reading still works
    res = await client.get(f"/api/v1/parts/revisions/{rid}/bom", headers=eng_auth)
    assert res.status_code == 200
    assert len(res.json()) == 1
