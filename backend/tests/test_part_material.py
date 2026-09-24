"""Material on the article: linked to MaterialDB or explicitly new."""
import pytest

pytestmark = pytest.mark.asyncio

MATERIAL_FIELDS = ("material_source", "materialdb_id", "material_ktx_number",
                   "material_label", "material_synced_at", "material_new_text")


async def _part(client, auth, seed, number="A-1", category="article"):
    body = {"project_id": seed["project_id"], "part_number": number, "name": number,
            "part_type": "internal_mfg", "item_category": category}
    r = await client.post("/api/v1/parts", json=body, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_new_part_has_no_material(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert {k: body[k] for k in MATERIAL_FIELDS} == {k: None for k in MATERIAL_FIELDS}


async def _changelog(client, auth, pid):
    return [e for e in (await client.get(f"/api/v1/parts/{pid}/changelog", headers=auth)).json()
            if e["action"].startswith("material_")]


async def test_pick_from_materialdb_stores_id_number_and_label(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                         headers=eng_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["material_source"] == "materialdb"
    assert (body["materialdb_id"], body["material_ktx_number"]) == (11, "40-1234")
    assert body["material_label"] == "40-1234 Ultramid B3WG6 black 00564"
    assert body["material_synced_at"] is not None and body["material_new_text"] is None
    log = await _changelog(client, eng_auth, pid)
    assert [(e["action"], e["new_value"]) for e in log] == [("material_set", "40-1234 Ultramid B3WG6 black 00564")]


async def test_pick_research_material_without_number(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 12},
                         headers=eng_auth)
    assert r.json()["material_ktx_number"] is None
    assert r.json()["material_label"] == "REZYcom PA6 RB122 F15 (research)"


async def test_new_material_is_marked_new(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                     headers=eng_auth)
    r = await client.put(f"/api/v1/parts/{pid}/material",
                         json={"source": "new", "new_text": "  PA6-GF15 acc. VW 50125 "}, headers=eng_auth)
    body = r.json()
    assert body["material_source"] == "new"
    assert body["material_new_text"] == "PA6-GF15 acc. VW 50125"
    assert (body["materialdb_id"], body["material_ktx_number"], body["material_label"]) == (None, None, None)
    log = await _changelog(client, eng_auth, pid)
    assert log[-1]["old_value"] == "40-1234 Ultramid B3WG6 black 00564"
    assert log[-1]["new_value"] == "NEW (not in MaterialDB): PA6-GF15 acc. VW 50125"


async def test_new_material_needs_text_and_materialdb_needs_an_id(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    assert (await client.put(f"/api/v1/parts/{pid}/material", json={"source": "new", "new_text": "  "},
                             headers=eng_auth)).status_code == 422
    assert (await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb"},
                             headers=eng_auth)).status_code == 422


async def test_clear_material(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "new", "new_text": "PP"}, headers=eng_auth)
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": None}, headers=eng_auth)
    assert r.status_code == 200
    assert r.json()["material_source"] is None and r.json()["material_new_text"] is None


async def test_tools_have_no_material(client, eng_auth, seed, materialdb):
    tid = await _part(client, eng_auth, seed, "T-1", "tool")
    r = await client.put(f"/api/v1/parts/{tid}/material", json={"source": "new", "new_text": "PP"}, headers=eng_auth)
    assert r.status_code == 400
    assert r.json()["detail"] == "Material applies to articles only"


async def test_unknown_materialdb_id_is_400(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 999},
                         headers=eng_auth)
    assert r.status_code == 400
    assert "999" in r.json()["detail"]


async def test_pick_when_unreachable_is_503_and_part_unchanged(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "new", "new_text": "PP"}, headers=eng_auth)
    materialdb["fail"] = "down"
    r = await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                         headers=eng_auth)
    assert r.status_code == 503
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert (body["material_source"], body["material_new_text"]) == ("new", "PP")


async def test_refresh_rereads_the_label(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                     headers=eng_auth)
    materialdb["items"][0]["grade"] = "black 00564 UV"
    r = await client.post(f"/api/v1/parts/{pid}/material/refresh", headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["material_label"] == "40-1234 Ultramid B3WG6 black 00564 UV"
    assert [e["action"] for e in await _changelog(client, eng_auth, pid)] == ["material_set", "material_refreshed"]


async def test_refresh_unreachable_keeps_label(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                     headers=eng_auth)
    materialdb["fail"] = "500"
    r = await client.post(f"/api/v1/parts/{pid}/material/refresh", headers=eng_auth)
    assert r.status_code == 503
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert body["material_label"] == "40-1234 Ultramid B3WG6 black 00564"


async def test_refresh_when_gone_is_409_and_keeps_label(client, eng_auth, seed, materialdb):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}/material", json={"source": "materialdb", "materialdb_id": 11},
                     headers=eng_auth)
    materialdb["items"] = [m for m in materialdb["items"] if m["id"] != 11]
    r = await client.post(f"/api/v1/parts/{pid}/material/refresh", headers=eng_auth)
    assert r.status_code == 409
    assert "no longer in MaterialDB" in r.json()["detail"]
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert body["material_label"] == "40-1234 Ultramid B3WG6 black 00564"


async def test_refresh_of_unlinked_material_is_400(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    r = await client.post(f"/api/v1/parts/{pid}/material/refresh", headers=eng_auth)
    assert r.status_code == 400
