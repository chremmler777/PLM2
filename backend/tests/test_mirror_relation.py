"""Tests for mirror_of relation type - one mirror per article, no chains."""
import pytest


async def _create(client, auth, seed, number, name, item_category="article", project_id=None):
    res = await client.post("/api/v1/parts", headers=auth, json={
        "project_id": project_id or seed["project_id"], "part_number": number, "name": name,
        "part_type": "internal_mfg", "data_classification": "confidential", "item_category": item_category})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _mirror(client, auth, mirror, source):
    return await client.post(f"/api/v1/parts/{mirror}/relations", headers=auth,
                             json={"to_part_id": source, "relation_type": "mirror_of"})


async def test_mirror_roundtrip_labels(client, eng_auth, seed):
    lh = await _create(client, eng_auth, seed, "20-1", "Handle LH")
    rh = await _create(client, eng_auth, seed, "20-2", "Handle RH")
    r = await _mirror(client, eng_auth, rh, lh)
    assert r.status_code == 201, r.text
    assert r.json()["label"] == "mirror of"
    src = (await client.get(f"/api/v1/parts/{lh}/relations", headers=eng_auth)).json()
    assert [(x["label"], x["other_part_number"]) for x in src] == [("mirrored by", "20-2")]
    mir = (await client.get(f"/api/v1/parts/{rh}/relations", headers=eng_auth)).json()
    assert [(x["label"], x["other_part_number"]) for x in mir] == [("mirror of", "20-1")]


async def test_one_mirror_per_part(client, eng_auth, seed):
    a = await _create(client, eng_auth, seed, "20-1", "A")
    b = await _create(client, eng_auth, seed, "20-2", "B")
    c = await _create(client, eng_auth, seed, "20-3", "C")
    assert (await _mirror(client, eng_auth, b, a)).status_code == 201
    r = await _mirror(client, eng_auth, b, c)
    assert r.status_code == 409
    assert "already a mirror" in r.json()["detail"]


async def test_mirror_must_be_articles(client, eng_auth, seed):
    a = await _create(client, eng_auth, seed, "20-1", "A")
    tool = await _create(client, eng_auth, seed, "T-1", "Tool", item_category="tool")
    r = await _mirror(client, eng_auth, tool, a)
    assert r.status_code == 400
    assert "articles" in r.json()["detail"]


async def test_mirror_chain_is_refused(client, eng_auth, seed):
    a = await _create(client, eng_auth, seed, "20-1", "A")
    b = await _create(client, eng_auth, seed, "20-2", "B")
    c = await _create(client, eng_auth, seed, "20-3", "C")
    assert (await _mirror(client, eng_auth, b, a)).status_code == 201
    r = await _mirror(client, eng_auth, c, b)
    assert r.status_code == 400
    assert "itself a mirror" in r.json()["detail"]
