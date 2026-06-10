"""Item relation tests - tool/gauge/equipment to article links."""


async def _create(client, eng_auth, seed, part_number, name, item_category="article"):
    res = await client.post(
        "/api/v1/parts",
        json={
            "project_id": seed["project_id"],
            "part_number": part_number,
            "name": name,
            "part_type": "purchased",
            "data_classification": "confidential",
            "item_category": item_category,
        },
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_relation_roundtrip(client, eng_auth, seed):
    article = await _create(client, eng_auth, seed, "A-10", "Housing")
    tool = await _create(client, eng_auth, seed, "T-10", "Injection Mold", "tool")
    gauge = await _create(client, eng_auth, seed, "G-10", "Caliper", "gauge")

    res = await client.post(
        f"/api/v1/parts/{tool}/relations",
        json={"to_part_id": article, "relation_type": "produces"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    assert res.json()["label"] == "produces"

    res = await client.post(
        f"/api/v1/parts/{gauge}/relations",
        json={"to_part_id": article, "relation_type": "checks"},
        headers=eng_auth,
    )
    assert res.status_code == 201

    # Article sees both incoming links with reversed labels
    res = await client.get(f"/api/v1/parts/{article}/relations", headers=eng_auth)
    rels = res.json()
    assert len(rels) == 2
    labels = {(r["label"], r["other_part_number"]) for r in rels}
    assert ("produced by", "T-10") in labels
    assert ("checked by", "G-10") in labels

    # Tool sees its outgoing link
    res = await client.get(f"/api/v1/parts/{tool}/relations", headers=eng_auth)
    assert res.json()[0]["direction"] == "outgoing"

    # Changelog recorded on the article
    res = await client.get(f"/api/v1/parts/{article}/changelog", headers=eng_auth)
    assert any(e["action"] == "relation_added" for e in res.json())

    # Delete
    rel_id = rels[0]["id"]
    res = await client.delete(f"/api/v1/parts/relations/{rel_id}", headers=eng_auth)
    assert res.status_code == 200
    res = await client.get(f"/api/v1/parts/{article}/relations", headers=eng_auth)
    assert len(res.json()) == 1


async def test_relation_guards(client, eng_auth, seed):
    a = await _create(client, eng_auth, seed, "A-20", "Part A")
    b = await _create(client, eng_auth, seed, "B-20", "Part B", "tool")

    # Self-relation
    res = await client.post(
        f"/api/v1/parts/{a}/relations",
        json={"to_part_id": a, "relation_type": "related"},
        headers=eng_auth,
    )
    assert res.status_code == 400

    # Invalid type
    res = await client.post(
        f"/api/v1/parts/{b}/relations",
        json={"to_part_id": a, "relation_type": "teleports"},
        headers=eng_auth,
    )
    assert res.status_code == 400

    # Duplicate
    res = await client.post(
        f"/api/v1/parts/{b}/relations",
        json={"to_part_id": a, "relation_type": "produces"},
        headers=eng_auth,
    )
    assert res.status_code == 201
    res = await client.post(
        f"/api/v1/parts/{b}/relations",
        json={"to_part_id": a, "relation_type": "produces"},
        headers=eng_auth,
    )
    assert res.status_code == 409
