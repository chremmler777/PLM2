"""HTTP client for the MachineDB service API (/v1).

MachineDB owns the press list (name, plant, clamping force, 2K type,
lifecycle dates). The cost sheet keeps a local copy (cost_sheet_machines)
that a sync refreshes; costing never calls MachineDB live, so an unreachable
MachineDB only stops the sync, never a costing.
/im-tools (list_im_tools) gives an injection tool's press tonnage for the
tool tonnage sync (tool_tonnage_service), stored on the tool part the same way.

Configuration (environment, never the database):
- MACHINEDB_API_URL: base URL of the service API, e.g.
  http://machinedb-backend:3001/v1 (docker-internal network) or an https
  route on the MachineDB host. The token rides every request: never plain
  http across hosts (rollout runbook, MachineDB section).
- MACHINEDB_SERVICE_TOKEN: the bearer token MachineDB's serviceAuth expects.
- MACHINEDB_TIMEOUT_S: optional request timeout in seconds (default 10).

The token is sent as a header and never logged or put into an error text.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0


class MachineDBUnavailable(Exception):
    """MachineDB is not configured, not reachable, or answered with an error.
    The message is safe to show to a user (no token, no response body)."""


@dataclass(frozen=True)
class MachineDTO:
    id: int
    internal_name: str
    plant: Optional[str]                  # lowercased: usa, mexico, weissenburg, ...
    clamping_force_t: Optional[float]
    tonnage_class: Optional[str]          # only when MachineDB sends one
    two_k_type: Optional[str]
    manufacturer: Optional[str]
    model: Optional[str]
    in_service_from: Optional[date]
    planned_scrap_from: Optional[date]
    updated_at: Optional[str]


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        logger.warning("MachineDB returned an unparseable date: %r", value)
        return None


def _parse_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s[:limit] or None


def from_api(row: dict) -> MachineDTO:
    """One /v1/machines row (MachineDB's mapRow shape). Raises KeyError /
    ValueError on a row without an id or a name."""
    name = _text(row.get("internal_name"), 120)
    if row.get("id") is None or not name:
        raise ValueError("machine row without id or internal_name")
    plant = _text(row.get("plant"), 40)
    return MachineDTO(
        id=int(row["id"]),
        internal_name=name,
        plant=plant.lower() if plant else None,
        clamping_force_t=_parse_float(row.get("clamping_force_t")),
        tonnage_class=_text(row.get("tonnage_class"), 20),
        two_k_type=_text(row.get("two_k_type"), 40),
        manufacturer=_text(row.get("manufacturer"), 120),
        model=_text(row.get("model"), 120),
        in_service_from=_parse_date(row.get("in_service_from")),
        planned_scrap_from=_parse_date(row.get("planned_scrap_from")),
        updated_at=_text(row.get("updated_at"), 40),
    )


def base_url() -> Optional[str]:
    url = (os.getenv("MACHINEDB_API_URL") or "").strip()
    return url.rstrip("/") or None


def _token() -> Optional[str]:
    return (os.getenv("MACHINEDB_SERVICE_TOKEN") or "").strip() or None


def _timeout() -> float:
    try:
        t = float(os.getenv("MACHINEDB_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    except ValueError:
        t = DEFAULT_TIMEOUT_S
    return t if 0 < t <= 120 else DEFAULT_TIMEOUT_S


def is_configured() -> bool:
    return base_url() is not None and _token() is not None


def config_status() -> dict:
    """What the UI may show: whether a sync can run and why not. Never the
    token, and only the host of the URL."""
    url, token = base_url(), _token()
    missing = [k for k, v in (("MACHINEDB_API_URL", url),
                              ("MACHINEDB_SERVICE_TOKEN", token)) if not v]
    host = None
    if url:
        try:
            host = httpx.URL(url).host or None
        except Exception:  # noqa: BLE001 - a malformed URL is reported as such
            host = None
    return {"configured": not missing, "missing": missing, "host": host}


async def _get(path: str, params: Optional[dict] = None,
               transport: Optional[httpx.AsyncBaseTransport] = None) -> Any:
    url, token = base_url(), _token()
    if not url or not token:
        raise MachineDBUnavailable(
            "MachineDB is not configured (MACHINEDB_API_URL and "
            "MACHINEDB_SERVICE_TOKEN must be set on the backend)")
    try:
        async with httpx.AsyncClient(timeout=_timeout(), transport=transport) as c:
            resp = await c.get(f"{url}{path}", params=params,
                               headers={"Authorization": f"Bearer {token}",
                                        "Accept": "application/json"})
    except httpx.TimeoutException:
        logger.warning("MachineDB timed out on %s", path)
        raise MachineDBUnavailable("MachineDB did not answer in time") from None
    except httpx.HTTPError as exc:
        # The exception text names the URL, never the header.
        logger.warning("MachineDB unreachable on %s: %s", path, type(exc).__name__)
        raise MachineDBUnavailable("MachineDB is not reachable from this server") from None
    if resp.status_code == 404:
        return None
    if resp.status_code in (401, 403):
        logger.warning("MachineDB refused the service token (%s)", resp.status_code)
        raise MachineDBUnavailable("MachineDB refused the service token")
    if resp.status_code >= 400:
        logger.warning("MachineDB returned %s on %s", resp.status_code, path)
        raise MachineDBUnavailable(f"MachineDB returned an error ({resp.status_code})")
    try:
        return resp.json()
    except ValueError:
        raise MachineDBUnavailable("MachineDB returned no JSON") from None


async def list_machines(*, transport: Optional[httpx.AsyncBaseTransport] = None
                        ) -> tuple[list[MachineDTO], list[str]]:
    """Every machine MachineDB knows (no filter: the sync decides), and the
    rows it could not read (as short texts for the sync report)."""
    data = await _get("/machines", transport=transport)
    if not isinstance(data, list):
        raise MachineDBUnavailable("MachineDB returned an unexpected machine list")
    out, bad = [], []
    for row in data:
        try:
            out.append(from_api(row))
        except (KeyError, TypeError, ValueError):
            bad.append(f"row {row.get('id') if isinstance(row, dict) else '?'}")
    return out, bad


async def get_machine(machine_id: int, *,
                      transport: Optional[httpx.AsyncBaseTransport] = None
                      ) -> Optional[MachineDTO]:
    data = await _get(f"/machines/{int(machine_id)}", transport=transport)
    return from_api(data) if isinstance(data, dict) else None


# ---------------------------------------------------------------- injection tools

# Tool numbers per /im-tools request: the list rides the query string.
IM_TOOLS_BATCH = 50


@dataclass(frozen=True)
class ImToolDTO:
    """One /v1/im-tools row: what MachineDB knows about an injection tool's
    press. The tonnage PLM2 costs on is `tonnage_t` (see there)."""
    tool_number: str
    qualified_min_tonnage_t: Optional[float]
    qualified_max_tonnage_t: Optional[float]
    assigned_machine_name: Optional[str]
    assigned_machine_plant: Optional[str]
    assigned_clamping_force_t: Optional[float]

    @property
    def tonnage_t(self) -> tuple[Optional[float], Optional[str]]:
        """(tonnage, basis). The press the tool is assigned to, by its
        clamping force ("assigned"); without one, the smallest press the tool
        is qualified on ("qualified_min"): the realistic cost basis, since the
        tool runs on the smallest press that can take it. (None, None) when
        MachineDB knows neither."""
        f = self.assigned_clamping_force_t
        if f is not None and f > 0:
            return f, "assigned"
        q = self.qualified_min_tonnage_t
        if q is not None and q > 0:
            return q, "qualified_min"
        return None, None


def im_tool_from_api(row: dict) -> ImToolDTO:
    number = _text(row.get("tool_number"), 100)
    if not number:
        raise ValueError("im-tool row without tool_number")
    m = row.get("assigned_machine") if isinstance(row.get("assigned_machine"), dict) else None
    return ImToolDTO(
        tool_number=number,
        qualified_min_tonnage_t=_parse_float(row.get("qualified_min_tonnage_t")),
        qualified_max_tonnage_t=_parse_float(row.get("qualified_max_tonnage_t")),
        assigned_machine_name=_text(m.get("internal_name"), 120) if m else None,
        assigned_machine_plant=_text(m.get("plant"), 40) if m else None,
        assigned_clamping_force_t=_parse_float(m.get("clamping_force_t")) if m else None,
    )


async def list_im_tools(tool_numbers: list[str], *,
                        transport: Optional[httpx.AsyncBaseTransport] = None
                        ) -> list[ImToolDTO]:
    """The MachineDB rows for these tool numbers (exact match on MachineDB's
    side: the caller sends every spelling it accepts). Batched; one failed
    batch fails the whole call (MachineDBUnavailable), so a caller never
    mistakes a half answer for a full one. An unreadable row is dropped."""
    numbers = sorted({n.strip() for n in tool_numbers if n and n.strip() and "," not in n})
    out: list[ImToolDTO] = []
    for i in range(0, len(numbers), IM_TOOLS_BATCH):
        data = await _get("/im-tools",
                          params={"tool_number": ",".join(numbers[i:i + IM_TOOLS_BATCH])},
                          transport=transport)
        if data is None:
            # 404: a MachineDB without the /v1/im-tools route (not deployed yet)
            raise MachineDBUnavailable("MachineDB has no /v1/im-tools route yet")
        if not isinstance(data, list):
            raise MachineDBUnavailable("MachineDB returned an unexpected tool list")
        for row in data:
            try:
                out.append(im_tool_from_api(row))
            except (AttributeError, TypeError, ValueError):
                logger.warning("MachineDB sent an unreadable im-tool row")
    return out
