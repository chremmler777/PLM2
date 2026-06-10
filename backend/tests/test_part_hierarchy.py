"""Part hierarchy and re-parenting tests."""


async def _make_part(client, eng_auth, seed, part_number, name, parent_part_id=None):
    payload = {
        "project_id": seed["project_id"],
        "part_number": part_number,
        "name": name,
        "part_type": "sub_assembly",
        "data_classification": "confidential",
    }
    if parent_part_id:
        payload["parent_part_id"] = parent_part_id
    res = await client.post("/api/v1/parts", json=payload, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_reparent_and_clear(client, eng_auth, seed):
    a = await _make_part(client, eng_auth, seed, "A-1", "Assembly A")
    b = await _make_part(client, eng_auth, seed, "B-1", "Component B")

    res = await client.put(f"/api/v1/parts/{b}", json={"parent_part_id": a}, headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["parent_part_id"] == a

    # Move back to top level with explicit null
    res = await client.put(f"/api/v1/parts/{b}", json={"parent_part_id": None}, headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["parent_part_id"] is None


async def test_self_parent_rejected(client, eng_auth, seed):
    a = await _make_part(client, eng_auth, seed, "A-2", "Assembly")
    res = await client.put(f"/api/v1/parts/{a}", json={"parent_part_id": a}, headers=eng_auth)
    assert res.status_code == 400


async def test_cycle_rejected(client, eng_auth, seed):
    a = await _make_part(client, eng_auth, seed, "A-3", "Root")
    b = await _make_part(client, eng_auth, seed, "B-3", "Child", parent_part_id=a)
    c = await _make_part(client, eng_auth, seed, "C-3", "Grandchild", parent_part_id=b)

    # Root under its own grandchild -> cycle
    res = await client.put(f"/api/v1/parts/{a}", json={"parent_part_id": c}, headers=eng_auth)
    assert res.status_code == 400


async def test_update_without_parent_field_keeps_parent(client, eng_auth, seed):
    a = await _make_part(client, eng_auth, seed, "A-4", "Assembly")
    b = await _make_part(client, eng_auth, seed, "B-4", "Component", parent_part_id=a)

    res = await client.put(f"/api/v1/parts/{b}", json={"name": "Renamed"}, headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["parent_part_id"] == a
    assert res.json()["name"] == "Renamed"
