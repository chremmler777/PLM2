"""Tier 1 part number: the number the Tier 1 (e.g. Brose) uses for a part,
kept apart from customer_part_number, which stays the OEM (VW) number."""


async def _create(client, eng_auth, seed, **extra):
    body = {
        "project_id": seed["project_id"],
        "part_number": "20-1994-003-0",
        "name": "206.887.233 Isofix cover",
        "part_type": "purchased",
        "data_classification": "confidential",
        "customer_part_number": "206.887.233",
        **extra,
    }
    res = await client.post("/api/v1/parts", json=body, headers=eng_auth)
    assert res.status_code == 200, res.text
    return res.json()


async def test_tier1_number_created_and_returned(client, eng_auth, seed):
    created = await _create(client, eng_auth, seed, tier1_part_number="S00H54-110")
    assert created["tier1_part_number"] == "S00H54-110"
    assert created["customer_part_number"] == "206.887.233"

    res = await client.get(f"/api/v1/parts/{created['id']}", headers=eng_auth)
    assert res.json()["tier1_part_number"] == "S00H54-110"


async def test_tier1_number_update_and_clear(client, eng_auth, seed):
    created = await _create(client, eng_auth, seed)
    assert created["tier1_part_number"] is None
    pid = created["id"]

    res = await client.put(f"/api/v1/parts/{pid}", json={"tier1_part_number": "S00H54-110"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["tier1_part_number"] == "S00H54-110"
    assert res.json()["customer_part_number"] == "206.887.233"

    # A body without the key leaves it alone
    res = await client.put(f"/api/v1/parts/{pid}", json={"name": "Isofix cover"}, headers=eng_auth)
    assert res.json()["tier1_part_number"] == "S00H54-110"

    # An explicit null clears it
    res = await client.put(f"/api/v1/parts/{pid}", json={"tier1_part_number": None}, headers=eng_auth)
    assert res.json()["tier1_part_number"] is None
