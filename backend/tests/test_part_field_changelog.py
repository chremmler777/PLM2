"""Editing tier1/customer part numbers, name, part_type and the tool fields
through PUT /api/v1/parts/{id} logs one changelog entry per changed field
(field_updated), matching the worksheet audit mapping. Unchanged values log
nothing, and toolmaker logs the supplier name."""
import pytest

from app.services.worksheet_audit import audit_field_key

pytestmark = pytest.mark.asyncio


async def _tool(client, eng_auth, seed, number="199403"):
    body = {"project_id": seed["project_id"], "part_number": number, "name": "ISOFIX Cover",
            "part_type": "purchased", "item_category": "tool"}
    r = await client.post("/api/v1/parts", json=body, headers=eng_auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _supplier(client, eng_auth, name="Toolshop Sued"):
    res = await client.post("/api/v1/suppliers", json={"name": name}, headers=eng_auth)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _log(client, auth, pid):
    return [(e["action"], e["field_name"], e["old_value"], e["new_value"])
            for e in (await client.get(f"/api/v1/parts/{pid}/changelog", headers=auth)).json()
            if e["action"] == "field_updated"]


async def test_tier1_and_customer_part_number_are_logged(client, eng_auth, seed):
    pid = await _tool(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}", json={"tier1_part_number": "T1-1"}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{pid}", json={"customer_part_number": "C-1"}, headers=eng_auth)
    # Same value again: no entry
    await client.put(f"/api/v1/parts/{pid}", json={"tier1_part_number": "T1-1"}, headers=eng_auth)
    assert await _log(client, eng_auth, pid) == [
        ("field_updated", "tier1_part_number", None, "T1-1"),
        ("field_updated", "customer_part_number", None, "C-1"),
    ]


async def test_name_and_part_type_are_logged(client, eng_auth, seed):
    pid = await _tool(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}", json={"name": "ISOFIX Cover 4-cav"}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{pid}", json={"part_type": "internal_mfg"}, headers=eng_auth)
    # Same value again: no entry
    await client.put(f"/api/v1/parts/{pid}", json={"name": "ISOFIX Cover 4-cav"}, headers=eng_auth)
    assert await _log(client, eng_auth, pid) == [
        ("field_updated", "name", "ISOFIX Cover", "ISOFIX Cover 4-cav"),
        ("field_updated", "part_type", "purchased", "internal_mfg"),
    ]


async def test_tool_fields_are_logged(client, eng_auth, seed):
    pid = await _tool(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": 4}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{pid}", json={"tool_tonnage_class": 650}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{pid}", json={"tool_cycle_time_s": 55.0}, headers=eng_auth)
    # No-op writes: no entries
    await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": 4}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{pid}", json={"name": "ISOFIX Cover"}, headers=eng_auth)
    assert await _log(client, eng_auth, pid) == [
        ("field_updated", "tool_cavities", None, "4"),
        ("field_updated", "tool_tonnage_class", None, "650"),
        ("field_updated", "tool_cycle_time_s", None, "55.0"),
    ]


async def test_toolmaker_change_logs_supplier_name(client, eng_auth, seed):
    pid = await _tool(client, eng_auth, seed)
    sued = await _supplier(client, eng_auth, "Toolshop Sued")
    nord = await _supplier(client, eng_auth, "Toolshop Nord")
    await client.put(f"/api/v1/parts/{pid}", json={"toolmaker_id": sued}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{pid}", json={"toolmaker_id": nord}, headers=eng_auth)
    assert await _log(client, eng_auth, pid) == [
        ("field_updated", "toolmaker_id", None, "Toolshop Sued"),
        ("field_updated", "toolmaker_id", "Toolshop Sued", "Toolshop Nord"),
    ]


async def test_new_fields_map_to_worksheet_audit_keys():
    assert audit_field_key("field_updated", "tier1_part_number") == "part.tier1_part_number"
    assert audit_field_key("field_updated", "customer_part_number") == "part.customer_part_number"
    assert audit_field_key("field_updated", "name") == "part.name"
    assert audit_field_key("field_updated", "part_type") == "part.part_type"
    assert audit_field_key("field_updated", "tool_cavities") == "tool.cavities"
    assert audit_field_key("field_updated", "tool_cycle_time_s") == "tool.cycle_time_s"
    assert audit_field_key("field_updated", "tool_tonnage_class") == "tool.tonnage_class"
    assert audit_field_key("field_updated", "toolmaker_id") == "tool.toolmaker"


async def test_worksheet_audit_returns_new_field_entries(client, eng_auth, seed):
    pid = await _tool(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}", json={"tool_cavities": 4}, headers=eng_auth)
    res = await client.get(f"/api/v1/projects/{seed['project_id']}/worksheet/audit", headers=eng_auth)
    assert res.status_code == 200, res.text
    entries = res.json()["entries"]
    matches = [e for e in entries if e["part"]["id"] == pid and e["field_key"] == "tool.cavities"]
    assert len(matches) == 1
    assert (matches[0]["old_value"], matches[0]["new_value"]) == (None, "4")
