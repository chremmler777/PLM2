"""PLM proxies MaterialDB search: the browser never sees the service token."""
import pytest

from app.core.config import get_settings
from app.services import materialdb_client

pytestmark = pytest.mark.asyncio


async def test_search_matches_all_tokens_and_puts_series_first(client, eng_auth, materialdb):
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert [m["id"] for m in r.json()] == [11, 12]
    assert r.json()[0] == {"id": 11, "ktx_number": "40-1234", "trade_name": "Ultramid B3WG6",
                           "grade": "black 00564", "manufacturer": "BASF", "family": "PA6",
                           "classification": "series", "label": "40-1234 Ultramid B3WG6 black 00564"}
    r = await client.get("/api/v1/materials/search", params={"q": "polykemi gf15"}, headers=eng_auth)
    assert [m["label"] for m in r.json()] == ["REZYcom PA6 RB122 F15 (research)"]
    r = await client.get("/api/v1/materials/search", params={"q": "40-20"}, headers=eng_auth)
    assert [m["id"] for m in r.json()] == [13]
    assert materialdb["auth"] == "Bearer svc-token"
    assert materialdb["url"] == "http://materialdb.test/v1/materials"


async def test_search_uses_the_cached_list(client, eng_auth, materialdb):
    await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    await client.get("/api/v1/materials/search", params={"q": "pp"}, headers=eng_auth)
    assert materialdb["calls"] == 1


async def test_short_query_returns_nothing_without_calling(client, eng_auth, materialdb):
    r = await client.get("/api/v1/materials/search", params={"q": " p "}, headers=eng_auth)
    assert r.json() == []
    assert materialdb["calls"] == 0


async def test_search_not_configured_is_503(client, eng_auth, monkeypatch):
    monkeypatch.setattr(get_settings(), "materialdb_base_url", "")
    materialdb_client.clear_cache()
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]


async def test_search_unreachable_is_503(client, eng_auth, materialdb):
    materialdb["fail"] = "down"
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 503
    assert "unreachable" in r.json()["detail"]


async def test_search_non_200_is_503(client, eng_auth, materialdb):
    materialdb["fail"] = "500"
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 503
    assert "500" in r.json()["detail"]


async def test_search_garbage_payload_is_503(client, eng_auth, materialdb):
    materialdb["items"] = {"not": "a list"}
    r = await client.get("/api/v1/materials/search", params={"q": "pa6"}, headers=eng_auth)
    assert r.status_code == 503


async def test_find_by_id_and_label(materialdb):
    assert (await materialdb_client.find_by_id(12))["trade_name"] == "REZYcom PA6 RB122 F15"
    assert await materialdb_client.find_by_id(999) is None
    assert materialdb_client.label({"ktx_number": "40-1", "trade_name": " X ", "grade": None}) == "40-1 X"
