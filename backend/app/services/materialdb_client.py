"""Read-only client for the MaterialDB service API (bearer MATERIALDB_SERVICE_TOKEN).

MaterialDB offers machine callers only GET /v1/materials (the full list) and
GET /v1/materials/{ktx_number}; research materials have no KTX number. PLM
therefore keeps the full list for CACHE_SECONDS and searches and looks up by
id here, so the browser never sees the token."""
import time
from typing import Optional

import httpx

from app.core.config import get_settings

CACHE_SECONDS = 60.0
TIMEOUT_SECONDS = 8.0
SEARCH_FIELDS = ("ktx_number", "trade_name", "grade", "manufacturer", "family", "iso_designation", "supplier")
# Tests swap in httpx.MockTransport; None uses the network.
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None
_cache: dict = {"at": 0.0, "items": None}


class MaterialDbUnavailable(Exception):
    """Not configured, unreachable or answering with an error. The message is shown to the user."""


def clear_cache() -> None:
    _cache["at"] = 0.0
    _cache["items"] = None


def label(m: dict) -> str:
    text = " ".join(str(m.get(k)).strip() for k in ("ktx_number", "trade_name", "grade")
                    if m.get(k) and str(m.get(k)).strip())
    return text if m.get("ktx_number") else f"{text} (research)"


def hit(m: dict) -> dict:
    return {"id": m.get("id"), "ktx_number": m.get("ktx_number"), "trade_name": m.get("trade_name"),
            "grade": m.get("grade"), "manufacturer": m.get("manufacturer"), "family": m.get("family"),
            "classification": m.get("classification"), "label": label(m)}


async def fetch_all(force: bool = False) -> list[dict]:
    settings = get_settings()
    base = settings.materialdb_base_url.strip().rstrip("/")
    if not base or not settings.materialdb_service_token:
        raise MaterialDbUnavailable(
            "MaterialDB is not configured on this PLM server (MATERIALDB_BASE_URL, MATERIALDB_SERVICE_TOKEN)")
    now = time.monotonic()
    if not force and _cache["items"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["items"]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=TRANSPORT) as client:
            resp = await client.get(f"{base}/v1/materials",
                                    headers={"Authorization": f"Bearer {settings.materialdb_service_token}"})
    except httpx.HTTPError as e:
        raise MaterialDbUnavailable(f"MaterialDB is unreachable ({type(e).__name__}); try again later") from e
    if resp.status_code != 200:
        raise MaterialDbUnavailable(f"MaterialDB answered {resp.status_code}; try again later")
    try:
        items = resp.json()
    except ValueError as e:
        raise MaterialDbUnavailable("MaterialDB answered with something that is not JSON") from e
    if not isinstance(items, list) or not all(isinstance(m, dict) and "id" in m for m in items):
        raise MaterialDbUnavailable("MaterialDB answered with an unexpected material list")
    _cache["at"] = now
    _cache["items"] = items
    return items


def _haystack(m: dict) -> str:
    return " ".join(str(m.get(k) or "") for k in SEARCH_FIELDS).lower()


async def search(q: str, limit: int = 20) -> list[dict]:
    tokens = (q or "").lower().split()
    if len("".join(tokens)) < 2:
        return []
    items = await fetch_all()
    found = [m for m in items if all(t in _haystack(m) for t in tokens)]
    found.sort(key=lambda m: (m.get("ktx_number") is None, m.get("ktx_number") or "",
                              str(m.get("trade_name") or "").lower()))
    return [hit(m) for m in found[:limit]]


async def find_by_id(material_id: int, force: bool = False) -> Optional[dict]:
    for m in await fetch_all(force=force):
        if m.get("id") == material_id:
            return m
    return None
