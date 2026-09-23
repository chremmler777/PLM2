"""Tool fields: cavities, toolmaker, tonnage class and target cycle time live
on the tool part (item_category = tool). They are refused on articles, and a
PUT only touches them when the key is in the body."""


async def _create(client, eng_auth, seed, item_category="tool", **extra):
    body = {
        "project_id": seed["project_id"],
        "part_number": "199403" if item_category == "tool" else "20-1994-003-0",
        "name": "ISOFIX Cover" if item_category == "tool" else "206.887.233 Isofix cover",
        "part_type": "purchased",
        "data_classification": "confidential",
        "item_category": item_category,
        **extra,
    }
    return await client.post("/api/v1/parts", json=body, headers=eng_auth)


async def _supplier(client, eng_auth, name="Toolshop Sued"):
    res = await client.post("/api/v1/suppliers", json={"name": name}, headers=eng_auth)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_tool_fields_created_and_returned(client, eng_auth, seed):
    toolmaker = await _supplier(client, eng_auth)
    res = await _create(client, eng_auth, seed, tool_cavities=4, toolmaker_id=toolmaker,
                        tool_tonnage_class=650, tool_cycle_time_s=32.5)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tool_cavities"] == 4
    assert body["toolmaker_id"] == toolmaker
    assert body["tool_tonnage_class"] == 650
    assert body["tool_cycle_time_s"] == 32.5

    res = await client.get(f"/api/v1/parts/{body['id']}", headers=eng_auth)
    assert res.json()["tool_cycle_time_s"] == 32.5


async def test_tool_fields_default_null(client, eng_auth, seed):
    res = await _create(client, eng_auth, seed)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tool_cavities"] is None
    assert body["toolmaker_id"] is None
    assert body["tool_tonnage_class"] is None
    assert body["tool_cycle_time_s"] is None


async def test_tool_fields_update_only_when_key_present(client, eng_auth, seed):
    pid = (await _create(client, eng_auth, seed)).json()["id"]

    res = await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": 4}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["tool_cavities"] == 4

    res = await client.put(f"/api/v1/parts/{pid}", json={"name": "ISOFIX Cover 4-cav"}, headers=eng_auth)
    assert res.json()["tool_cavities"] == 4

    res = await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": None}, headers=eng_auth)
    assert res.json()["tool_cavities"] is None


async def test_tool_fields_rejected_on_article(client, eng_auth, seed):
    res = await _create(client, eng_auth, seed, item_category="article", tool_cavities=2)
    assert res.status_code == 400
    assert "tool" in res.json()["detail"].lower()

    pid = (await _create(client, eng_auth, seed, item_category="article")).json()["id"]
    res = await client.put(f"/api/v1/parts/{pid}", json={"tool_tonnage_class": 650}, headers=eng_auth)
    assert res.status_code == 400
    # Explicit null is still a tool-field write and is refused too
    res = await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": None}, headers=eng_auth)
    assert res.status_code == 400


async def test_toolmaker_must_be_a_supplier(client, eng_auth, seed):
    pid = (await _create(client, eng_auth, seed)).json()["id"]
    res = await client.put(f"/api/v1/parts/{pid}", json={"toolmaker_id": 999999}, headers=eng_auth)
    assert res.status_code == 400
    assert "toolmaker" in res.json()["detail"].lower()


async def test_tool_field_bounds(client, eng_auth, seed):
    pid = (await _create(client, eng_auth, seed)).json()["id"]
    assert (await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": 0}, headers=eng_auth)).status_code == 422
    assert (await client.put(f"/api/v1/parts/{pid}", json={"tool_cycle_time_s": -1}, headers=eng_auth)).status_code == 422
