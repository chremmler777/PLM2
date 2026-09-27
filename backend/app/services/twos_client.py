"""HTTP client for the TWOS /v1 service API (tools only).

TWOS keeps the tool list with the press each tool runs on (`press`, a
tonnage as text: "1,300"; "0" or "" means TWOS does not know). plm2 reads it
only for the tool tonnage sync (tool_tonnage_service), the second source
after MachineDB; costing never calls TWOS live.

Configuration (environment, never the database; both unset = TWOS skipped):
- TWOS_API_URL: base URL of the service API, e.g.
  http://twos-backend:8000/v1 (docker-internal) or an https route. The token
  rides every request: never plain http across hosts.
- TWOS_SERVICE_TOKEN: the bearer token TWOS's service router expects (the
  one PDB uses).
- TWOS_TIMEOUT_S: optional request timeout in seconds (default 10).

The token is sent as a header and never logged or put into an error text.
The tool list is cached for a minute (request smoothing, like PDB's client):
a refresh of many changes in a row asks TWOS once.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0
CACHE_TTL_S = 60.0


class TwosUnavailable(Exception):
    """TWOS is not configured, not reachable, or answered with an error.
    The message is safe to show to a user (no token, no response body)."""


@dataclass(frozen=True)
class TwosToolDTO:
    tool_number: str
    press_t: Optional[float]      # None: TWOS does not know ("0", "", unreadable)
    press_raw: Optional[str]


_NUM = re.compile(r"^\s*(\d[\d,]*(?:\.\d+)?)\s*(?:t|to|tons?)?\s*$", re.IGNORECASE)


def parse_press(value: Any) -> Optional[float]:
    """TWOS's press text as tonnes: "1,300" -> 1300.0, "350" -> 350.0,
    "450 t" -> 450.0; "0", "", None or text that is not a tonnage -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
    else:
        m = _NUM.match(str(value))
        if not m:
            return None
        try:
            f = float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return f if 0 < f < 100000 else None


def tool_from_api(row: dict) -> TwosToolDTO:
    number = row.get("tool_number")
    if number is None or not str(number).strip():
        raise ValueError("TWOS tool row without tool_number")
    raw = row.get("press")
    return TwosToolDTO(tool_number=str(number).strip()[:100],
                       press_t=parse_press(raw),
                       press_raw=None if raw is None else str(raw)[:40])


def base_url() -> Optional[str]:
    url = (os.getenv("TWOS_API_URL") or "").strip()
    return url.rstrip("/") or None


def _token() -> Optional[str]:
    return (os.getenv("TWOS_SERVICE_TOKEN") or "").strip() or None


def _timeout() -> float:
    try:
        t = float(os.getenv("TWOS_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    except ValueError:
        t = DEFAULT_TIMEOUT_S
    return t if 0 < t <= 120 else DEFAULT_TIMEOUT_S


def is_configured() -> bool:
    return base_url() is not None and _token() is not None


def config_status() -> dict:
    """Whether the sync can ask TWOS, and only the host of the URL."""
    url, token = base_url(), _token()
    missing = [k for k, v in (("TWOS_API_URL", url), ("TWOS_SERVICE_TOKEN", token)) if not v]
    host = None
    if url:
        try:
            host = httpx.URL(url).host or None
        except Exception:  # noqa: BLE001 - a malformed URL is reported as such
            host = None
    return {"configured": not missing, "missing": missing, "host": host}


_cache: dict[str, tuple[float, Any]] = {}


def clear_cache() -> None:
    _cache.clear()


async def _get(path: str, transport: Optional[httpx.AsyncBaseTransport] = None) -> Any:
    url, token = base_url(), _token()
    if not url or not token:
        raise TwosUnavailable("TWOS is not configured (TWOS_API_URL and "
                              "TWOS_SERVICE_TOKEN must be set on the backend)")
    try:
        async with httpx.AsyncClient(timeout=_timeout(), transport=transport) as c:
            resp = await c.get(f"{url}{path}",
                               headers={"Authorization": f"Bearer {token}",
                                        "Accept": "application/json"})
    except httpx.TimeoutException:
        logger.warning("TWOS timed out on %s", path)
        raise TwosUnavailable("TWOS did not answer in time") from None
    except httpx.HTTPError as exc:
        logger.warning("TWOS unreachable on %s: %s", path, type(exc).__name__)
        raise TwosUnavailable("TWOS is not reachable from this server") from None
    if resp.status_code in (401, 403):
        logger.warning("TWOS refused the service token (%s)", resp.status_code)
        raise TwosUnavailable("TWOS refused the service token")
    if resp.status_code >= 400:
        logger.warning("TWOS returned %s on %s", resp.status_code, path)
        raise TwosUnavailable(f"TWOS returned an error ({resp.status_code})")
    try:
        return resp.json()
    except ValueError:
        raise TwosUnavailable("TWOS returned no JSON") from None


async def list_tools(*, transport: Optional[httpx.AsyncBaseTransport] = None,
                     fresh: bool = False) -> list[TwosToolDTO]:
    """Every TWOS tool with its press tonnage (cached CACHE_TTL_S). An
    unreadable row is dropped. `fresh` skips the cache (a manual Refresh
    must not answer with data up to a minute old) and stores the answer."""
    hit = _cache.get("tools")
    if (transport is None and not fresh and hit
            and time.monotonic() - hit[0] < CACHE_TTL_S):
        return hit[1]
    data = await _get("/tools", transport=transport)
    if not isinstance(data, list):
        raise TwosUnavailable("TWOS returned an unexpected tool list")
    out = []
    for row in data:
        try:
            out.append(tool_from_api(row))
        except (AttributeError, TypeError, ValueError):
            logger.warning("TWOS sent an unreadable tool row")
    if transport is None:
        _cache["tools"] = (time.monotonic(), out)
    return out
