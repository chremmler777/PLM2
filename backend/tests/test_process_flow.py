"""Process flow is derived from serves/feeds relations, never from number
prefixes: tool 3455's punch-and-weld is numbered 3454-30 and is reachable only
through the relation."""
import pytest

pytestmark = pytest.mark.asyncio


async def _tool(client, auth, seed, number, name, category="tool"):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": name,
        "part_type": "purchased", "item_category": category,
    }, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_serves_relation_is_accepted_and_labelled(client, admin_auth, seed):
    gauge = await _tool(client, admin_auth, seed, "3454-40", "gauge", "gauge")
    tool = await _tool(client, admin_auth, seed, "3454", "Rear Cladding")

    res = await client.post(f"/api/v1/parts/{gauge}/relations", json={
        "to_part_id": tool, "relation_type": "serves"}, headers=admin_auth)
    assert res.status_code == 201, res.text
    assert res.json()["label"] == "serves"

    rows = (await client.get(f"/api/v1/parts/{tool}/relations",
                             headers=admin_auth)).json()
    served_by = [r for r in rows if r["relation_type"] == "serves"]
    assert served_by and served_by[0]["label"] == "served by"


async def test_feeds_relation_is_accepted_and_labelled(client, admin_auth, seed):
    upstream = await _tool(client, admin_auth, seed, "3457", "PDC Brackets")
    downstream = await _tool(client, admin_auth, seed, "3454", "Rear Cladding")

    res = await client.post(f"/api/v1/parts/{upstream}/relations", json={
        "to_part_id": downstream, "relation_type": "feeds",
        "notes": "2 brackets"}, headers=admin_auth)
    assert res.status_code == 201, res.text
    assert res.json()["label"] == "feeds"


async def _relate(client, auth, from_id, to_id, rel_type, notes=None):
    res = await client.post(f"/api/v1/parts/{from_id}/relations", json={
        "to_part_id": to_id, "relation_type": rel_type, "notes": notes},
        headers=auth)
    assert res.status_code == 201, res.text


async def _vw426_cell(client, auth, seed):
    """3454 + 3455 share a punch-and-weld; 3457 feeds both; 3454-40 gauges both."""
    ids = {}
    for number, name, cat in [
        ("3454", "Rear Cladding Basis", "tool"),
        ("3455", "Rear Cladding Peak", "tool"),
        ("3457", "PDC Brackets", "tool"),
        ("3454-30", "Punch & weld station", "assembly_equipment"),
        ("3454-40", "Rear Cladding gauge", "gauge"),
    ]:
        ids[number] = await _tool(client, auth, seed, number, name, cat)
    for tool in ("3454", "3455", "3457"):
        await _relate(client, auth, ids["3454-30"], ids[tool], "serves")
    for tool in ("3454", "3455"):
        await _relate(client, auth, ids["3454-40"], ids[tool], "serves")
    await _relate(client, auth, ids["3457"], ids["3454"], "feeds", "2 brackets")
    await _relate(client, auth, ids["3457"], ids["3455"], "feeds", "2 brackets")
    return ids


async def test_flow_orders_stations_by_op_code(client, admin_auth, seed):
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3454']}/process-flow",
                             headers=admin_auth)).json()
    assert body["tool"]["part_number"] == "3454"
    assert [s["op_code"] for s in body["stations"]] == ["30", "40"]
    assert body["stations"][1]["kind"] == "gauge"


async def test_shared_station_appears_on_the_tool_it_does_not_own(
        client, admin_auth, seed):
    """3455 owns no equipment; its station is numbered 3454-30. Prefix matching
    would show an empty process — the serves relation must drive it."""
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3455']}/process-flow",
                             headers=admin_auth)).json()
    assert [s["part_number"] for s in body["stations"]] == ["3454-30", "3454-40"]


async def test_upstream_feeds_are_listed_with_their_note(client, admin_auth, seed):
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3454']}/process-flow",
                             headers=admin_auth)).json()
    assert [u["part_number"] for u in body["upstream"]] == ["3457"]
    assert body["upstream"][0]["note"] == "2 brackets"


async def test_downstream_is_listed_for_the_feeding_tool(client, admin_auth, seed):
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3457']}/process-flow",
                             headers=admin_auth)).json()
    assert sorted(d["part_number"] for d in body["downstream"]) == ["3454", "3455"]


async def test_asking_from_an_equipment_part_resolves_to_its_tool(
        client, admin_auth, seed):
    ids = await _vw426_cell(client, admin_auth, seed)
    body = (await client.get(f"/api/v1/parts/{ids['3454-40']}/process-flow",
                             headers=admin_auth)).json()
    assert body["tool"]["part_number"] == "3454"


async def test_tool_with_no_equipment_returns_an_empty_flow(client, admin_auth, seed):
    lone = await _tool(client, admin_auth, seed, "3999", "Lonely tool")
    body = (await client.get(f"/api/v1/parts/{lone}/process-flow",
                             headers=admin_auth)).json()
    assert body["stations"] == []
    assert body["upstream"] == []


async def test_unknown_part_is_404(client, admin_auth, seed):
    res = await client.get("/api/v1/parts/999999/process-flow", headers=admin_auth)
    assert res.status_code == 404
