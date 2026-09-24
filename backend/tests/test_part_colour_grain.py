"""Colour code (the MIC colour of an unpainted article, e.g. NM0) and grain
(e.g. KF8) on the article: set through the part update, trimmed, empty
clears, articles only, one changelog entry per change."""
import pytest

from app.models.part import Part
from app.services.field_note_service import FieldNoteService

pytestmark = pytest.mark.asyncio


async def _part(client, auth, seed, number="A-1", category="article"):
    body = {"project_id": seed["project_id"], "part_number": number, "name": number,
            "part_type": "internal_mfg", "item_category": category}
    r = await client.post("/api/v1/parts", json=body, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _log(client, auth, pid):
    return [(e["action"], e["field_name"], e["old_value"], e["new_value"])
            for e in (await client.get(f"/api/v1/parts/{pid}/changelog", headers=auth)).json()
            if e["action"] == "field_updated"]


async def test_new_article_has_no_colour_code_or_grain(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    body = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert (body["colour_code"], body["grain"]) == (None, None)


async def test_set_trim_keep_and_clear(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    r = await client.put(f"/api/v1/parts/{pid}", json={"colour_code": "  NM0 ", "grain": " KF8 "}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert (r.json()["colour_code"], r.json()["grain"]) == ("NM0", "KF8")

    # A body without the keys leaves them alone
    r = await client.put(f"/api/v1/parts/{pid}", json={"name": "Renamed"}, headers=eng_auth)
    assert (r.json()["colour_code"], r.json()["grain"]) == ("NM0", "KF8")

    # Empty string and null clear
    r = await client.put(f"/api/v1/parts/{pid}", json={"colour_code": "   ", "grain": None}, headers=eng_auth)
    assert (r.json()["colour_code"], r.json()["grain"]) == (None, None)


async def test_every_change_is_logged_and_same_value_is_not(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    await client.put(f"/api/v1/parts/{pid}", json={"colour_code": "NM0"}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{pid}", json={"colour_code": "NM0", "grain": "KF8"}, headers=eng_auth)
    await client.put(f"/api/v1/parts/{pid}", json={"grain": ""}, headers=eng_auth)
    assert await _log(client, eng_auth, pid) == [
        ("field_updated", "colour_code", None, "NM0"),
        ("field_updated", "grain", None, "KF8"),
        ("field_updated", "grain", "KF8", None),
    ]


@pytest.mark.parametrize("category", ["tool", "gauge"])
async def test_only_articles_take_colour_code_and_grain(client, eng_auth, seed, category):
    pid = await _part(client, eng_auth, seed, "T-1", category)
    for field in ("colour_code", "grain"):
        r = await client.put(f"/api/v1/parts/{pid}", json={field: "X"}, headers=eng_auth)
        assert r.status_code == 400, r.text
        assert "articles" in r.json()["detail"]
    # Clearing is harmless on any category
    r = await client.put(f"/api/v1/parts/{pid}", json={"grain": None}, headers=eng_auth)
    assert r.status_code == 200, r.text


async def test_lengths_are_limited(client, eng_auth, seed):
    pid = await _part(client, eng_auth, seed)
    assert (await client.put(f"/api/v1/parts/{pid}", json={"colour_code": "x" * 41}, headers=eng_auth)).status_code == 422
    assert (await client.put(f"/api/v1/parts/{pid}", json={"grain": "x" * 81}, headers=eng_auth)).status_code == 422


async def test_field_keys_are_valid_note_keys(session_factory, seed):
    async with session_factory() as s:
        p = Part(project_id=seed["project_id"], part_number="A-9", name="A-9", part_type="internal_mfg",
                 item_category="article", created_by=seed["engineer_id"])
        s.add(p)
        await s.flush()
        for key in ("part.colour_code", "part.grain"):
            await FieldNoteService.add_comment(s, p, key, "check drawing", seed["engineer_id"])
        await s.commit()


async def test_create_takes_them_on_articles_only(client, eng_auth, seed):
    base = {"project_id": seed["project_id"], "name": "x", "part_type": "internal_mfg"}
    r = await client.post("/api/v1/parts", json={**base, "part_number": "A-2", "colour_code": " NM0 ", "grain": ""},
                          headers=eng_auth)
    assert r.status_code in (200, 201), r.text
    assert (r.json()["colour_code"], r.json()["grain"]) == ("NM0", None)
    r = await client.post("/api/v1/parts", json={**base, "part_number": "T-2", "item_category": "tool",
                                                 "grain": "KF8"}, headers=eng_auth)
    assert r.status_code == 400, r.text
