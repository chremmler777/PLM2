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
