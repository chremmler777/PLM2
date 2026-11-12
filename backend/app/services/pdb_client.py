"""HTTP client for PDB's read-only PLM service endpoints (project LOP).

    GET {pdb_api_url}/service/plm/projects/{project_id}/status
    GET {pdb_api_url}/service/plm/projects/{project_id}/topics

PDB has no /api/v1 prefix. Configuration (settings, from the environment):
PDB_API_URL (default http://pdb-backend:8000) and PDB_SERVICE_TOKEN (empty =
PDB is not configured). The token is sent as a bearer header and never logged
or put into an error text. Answers are cached for a minute per project and kind (also with a transport,
so tests can exercise the cache; tests call clear_cache()).

A project's PDB id is its project number (`projects.code`) when that is all
digits; any other code has no PDB project and makes no request.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT_S = 10.0
CACHE_TTL_S = 60.0

# Tests set this to route every request through an httpx.MockTransport (the
# routes call the client without a transport argument). Never set in production.
default_transport: Optional[httpx.AsyncBaseTransport] = None


class PdbUnavailable(Exception):
    """PDB is not configured, has no such project, is unreachable, or answered
    with an error. The message is safe to show (no token, no response body)."""


def is_configured() -> bool:
    return bool((get_settings().pdb_service_token or "").strip())


def pdb_project_id(project_code: str) -> int:
    code = (project_code or "").strip()
    if not (code.isascii() and code.isdigit()):
        raise PdbUnavailable("no PDB project for this code")
    return int(code)


_cache: dict[tuple[str, int], tuple[float, Any]] = {}


def clear_cache() -> None:
    _cache.clear()


async def _get(kind: str, project_code: str,
               transport: Optional[httpx.AsyncBaseTransport]) -> Any:
    settings = get_settings()
    token = (settings.pdb_service_token or "").strip()
    base = (settings.pdb_api_url or "").strip().rstrip("/")
    if not token or not base:
        raise PdbUnavailable("PDB is not configured (PDB_SERVICE_TOKEN is not set)")
    pid = pdb_project_id(project_code)
    explicit = transport if transport is not None else default_transport
    hit = _cache.get((kind, pid))
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    path = f"/service/plm/projects/{pid}/{kind}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=explicit) as c:
            resp = await c.get(f"{base}{path}",
                               headers={"Authorization": f"Bearer {token}",
                                        "Accept": "application/json"})
    except httpx.TimeoutException:
        logger.warning("PDB timed out on %s", path)
        raise PdbUnavailable("PDB did not answer in time") from None
    except httpx.HTTPError as exc:
        logger.warning("PDB unreachable on %s: %s", path, type(exc).__name__)
        raise PdbUnavailable("PDB is not reachable from this server") from None
    if resp.status_code in (401, 403):
        logger.warning("PDB refused the service token (%s)", resp.status_code)
        raise PdbUnavailable("PDB refused the service token")
    if resp.status_code == 404:
        raise PdbUnavailable("PDB has no project with this number")
    if resp.status_code == 503:
        raise PdbUnavailable("PDB cannot reach TWOS right now")
    if resp.status_code >= 400:
        logger.warning("PDB returned %s on %s", resp.status_code, path)
        raise PdbUnavailable(f"PDB returned an error ({resp.status_code})")
    try:
        data = resp.json()
    except ValueError:
        raise PdbUnavailable("PDB returned no JSON") from None
    _cache[(kind, pid)] = (time.monotonic(), data)
    return data


async def project_status(project_code: str, *,
                         transport: Optional[httpx.AsyncBaseTransport] = None) -> dict:
    """{"tool_count", "funnel", "tools": [...]} for the project."""
    data = await _get("status", project_code, transport)
    if not isinstance(data, dict):
        raise PdbUnavailable("PDB returned an unexpected status")
    return data


async def project_topics(project_code: str, *,
                         transport: Optional[httpx.AsyncBaseTransport] = None) -> list[dict]:
    """The project's open topics (unreadable rows are dropped)."""
    data = await _get("topics", project_code, transport)
    if not isinstance(data, list):
        raise PdbUnavailable("PDB returned an unexpected topic list")
    return [t for t in data if isinstance(t, dict) and t.get("id") is not None]
