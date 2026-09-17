"""GET /equipment?tool_number=N — the stations serving a tool, keyed by tool
number instead of part id. Built for the import client: same station rows as
the process flow, no upstream/downstream, gauges opt-in."""
import pytest

from tests.test_process_flow import _tool, _vw426_cell

pytestmark = pytest.mark.asyncio


async def test_stations_for_a_tool_exclude_gauges_by_default(client, admin_auth, seed):
    await _vw426_cell(client, admin_auth, seed)
    res = await client.get("/api/v1/equipment", params={"tool_number": "3454"},
                           headers=admin_auth)
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["part_number"] for r in rows] == ["3454-30"]
    row = rows[0]
    assert row["name"] == "Punch & weld station"
    assert row["op_code"] == "30"
    assert row["kind"] == "secondary_station"
    assert row["serves"] == ["3454", "3455", "3457"]
    assert "upstream" not in row and "downstream" not in row


async def test_include_gauges_adds_the_gauge_rows(client, admin_auth, seed):
    await _vw426_cell(client, admin_auth, seed)
    res = await client.get("/api/v1/equipment",
                           params={"tool_number": "3454", "include_gauges": "true"},
                           headers=admin_auth)
    assert res.status_code == 200, res.text
    assert [(r["part_number"], r["kind"]) for r in res.json()] == [
        ("3454-30", "secondary_station"), ("3454-40", "gauge")]


async def test_shared_station_is_returned_for_the_tool_that_does_not_own_it(
        client, admin_auth, seed):
    await _vw426_cell(client, admin_auth, seed)
    res = await client.get("/api/v1/equipment", params={"tool_number": "3455"},
                           headers=admin_auth)
    assert [r["part_number"] for r in res.json()] == ["3454-30"]


async def test_tool_with_no_equipment_is_an_empty_list(client, admin_auth, seed):
    await _tool(client, admin_auth, seed, "3999", "Lonely tool")
    res = await client.get("/api/v1/equipment", params={"tool_number": "3999"},
                           headers=admin_auth)
    assert res.status_code == 200
    assert res.json() == []


async def test_unknown_tool_is_404(client, admin_auth, seed):
    res = await client.get("/api/v1/equipment", params={"tool_number": "0000"},
                           headers=admin_auth)
    assert res.status_code == 404


async def test_short_tool_number_is_zero_padded(client, admin_auth, seed):
    """The PLM stores 4-char numbers ('0745'); the sheets write '745'."""
    await _tool(client, admin_auth, seed, "0745", "Padded tool")
    res = await client.get("/api/v1/equipment", params={"tool_number": "745"},
                           headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_tool_number_is_required(client, admin_auth, seed):
    res = await client.get("/api/v1/equipment", headers=admin_auth)
    assert res.status_code == 422


async def test_requires_auth(client, seed):
    res = await client.get("/api/v1/equipment", params={"tool_number": "3454"})
    assert res.status_code == 401
