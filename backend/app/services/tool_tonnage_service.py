"""The press tonnage of a change's tools, and the sync that keeps it.

Costing prices machine time and sampling on a machine class; with no class
picked by hand, the class is derived from the tonnage of the tools the
change touches (costing_rates.default_machine_class). This module answers
"which tools, and how big a press":

- the tools of a change: the impacted items that are tools themselves, and
  the tools that produce an impacted article (part_relations 'produces',
  tool -> article);
- the tonnage of one tool (tool_tonnage): MachineDB first, TWOS second, the
  tonnage typed on the tool in plm2 (parts.tool_tonnage_class) last. The
  change's tonnage is the largest over its tools (the biggest press sets the
  cost basis), with the tool it came from as provenance.

The MachineDB and TWOS values are a local copy on the tool part (108),
filled by sync_tools: at backend start (configured environments), by the
"Refresh tool tonnage" action (Sales, Finance, admins for the organisation;
whoever may set a change's class for that change's tools), and in the
background after a change's impacted items change. Costing never calls
MachineDB or TWOS: an unreachable source only stops the sync.

Guarded like the MachineDB machine sync: a source that is not configured,
fails, or answers without a usable tonnage for a tool leaves that tool's
stored value as it was. A sync writes values, it never clears one.

Matching: a tool part's part_number is the tool number the source systems
use. The exact spelling wins. PLM2 stores short numbers zero-padded to four
digits ("0745") where the sheets and TWOS write "745", so an all-digit
number of up to four digits with no exact row falls back to the row that
differs only by leading zeros (ProcessFlowService.find_tool's rule, in both
directions). Longer numbers match exactly: "012345" is not "12345".
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Part, PartRelation
from app.services import machinedb_client, twos_client
from app.services.equipment_numbering import TOOL_WIDTH

logger = logging.getLogger(__name__)

SOURCES = ("machinedb", "twos", "plm2")


# ---------------------------------------------------------------- matching

def exact_key(number: Optional[str]) -> str:
    """The number as the source spells it, trimmed and upper-cased."""
    return (number or "").strip().upper()


def number_key(number: Optional[str]) -> Optional[str]:
    """The key two spellings of one short tool number share: "0745", "745"
    and " 745 " -> "0745" (zero-padded to TOOL_WIDTH). Only all-digit
    numbers of up to TOOL_WIDTH digits have one, as in
    ProcessFlowService.find_tool: "012345" and "12345" are two tools, and
    so is anything not all digits. None when the number has no such key."""
    s = exact_key(number)
    if s.isdigit() and len(s) <= TOOL_WIDTH:
        return s.zfill(TOOL_WIDTH)
    return None


def spellings(number: str) -> set[str]:
    """Every spelling to ask an exact-match source for: as stored, and for a
    short all-digit number every spelling number_key folds together ("745",
    "0745"; "45", "045", "0045")."""
    s = (number or "").strip()
    out = {s} if s else set()
    if number_key(s) is not None:
        core = s.lstrip("0") or "0"
        out |= {core.zfill(n) for n in range(len(core), TOOL_WIDTH + 1)}
    return out


# ---------------------------------------------------------------- one tool

@dataclass(frozen=True)
class ToolTonnage:
    tool_id: int
    tool_number: str
    tonnage: float
    source: str                     # machinedb | twos | plm2
    basis: Optional[str] = None     # MachineDB: assigned | qualified_min
    machine: Optional[str] = None   # MachineDB: the assigned press
    fetched_at: Optional[datetime] = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["fetched_at"] = self.fetched_at.isoformat(timespec="seconds") if self.fetched_at else None
        return d


def tool_tonnage(tool: Part) -> Optional[ToolTonnage]:
    """The tool's tonnage: MachineDB, else TWOS, else typed in plm2."""
    if tool.tool_tonnage_mdb_t:
        return ToolTonnage(tool.id, tool.part_number, float(tool.tool_tonnage_mdb_t),
                           "machinedb", tool.tool_tonnage_mdb_basis,
                           tool.tool_tonnage_mdb_machine, tool.tool_tonnage_mdb_at)
    if tool.tool_tonnage_twos_t:
        return ToolTonnage(tool.id, tool.part_number, float(tool.tool_tonnage_twos_t),
                           "twos", fetched_at=tool.tool_tonnage_twos_at)
    if tool.tool_tonnage_class:
        return ToolTonnage(tool.id, tool.part_number, float(tool.tool_tonnage_class), "plm2")
    return None


# ---------------------------------------------------------------- a change's tools

async def tools_by_change(db: AsyncSession, change_ids: Iterable[int]) -> dict[int, list[Part]]:
    """{change id: its tools}, two queries for any number of changes: the
    impacted tools, and the tools producing an impacted article. Each list
    ordered by tool number, without duplicates."""
    from app.models.change import ChangeImpactedItem
    ids = list({int(i) for i in change_ids})
    out: dict[int, dict[int, Part]] = {cid: {} for cid in ids}
    if not ids:
        return {}
    impacted = (await db.execute(
        select(ChangeImpactedItem.change_id, Part)
        .join(Part, Part.id == ChangeImpactedItem.part_id)
        .where(ChangeImpactedItem.change_id.in_(ids)))).all()
    articles: dict[int, set[int]] = {}
    for cid, part in impacted:
        if part.item_category == "tool":
            out[cid][part.id] = part
        else:
            articles.setdefault(part.id, set()).add(cid)
    if articles:
        produced = (await db.execute(
            select(PartRelation.to_part_id, Part)
            .join(Part, Part.id == PartRelation.from_part_id)
            .where(PartRelation.to_part_id.in_(list(articles)),
                   PartRelation.relation_type == "produces",
                   Part.item_category == "tool"))).all()
        for article_id, tool in produced:
            for cid in articles.get(article_id, ()):
                out[cid][tool.id] = tool
    return {cid: sorted(tools.values(), key=lambda p: p.part_number)
            for cid, tools in out.items()}


@dataclass(frozen=True)
class ChangeTonnage:
    best: Optional[ToolTonnage]          # the largest tonnage over the tools
    tools: list[str]                     # every tool number of the change
    without: list[str]                   # tools no source has a tonnage for

    @property
    def tonnage(self) -> Optional[float]:
        return self.best.tonnage if self.best else None


def change_tonnage_of(tools: list[Part]) -> ChangeTonnage:
    known = [(t, tool_tonnage(t)) for t in tools]
    with_t = [tt for _, tt in known if tt is not None]
    # the largest; a tie goes to the better source, then the first tool
    # (tools come ordered by number; max keeps the first of equals)
    best = max(with_t, key=lambda tt: (tt.tonnage, -SOURCES.index(tt.source)),
               default=None)
    return ChangeTonnage(best=best, tools=[t.part_number for t in tools],
                         without=[t.part_number for t, tt in known if tt is None])


async def change_tonnage(db: AsyncSession, change) -> ChangeTonnage:
    if getattr(change, "id", None) is None:
        return ChangeTonnage(None, [], [])
    return change_tonnage_of((await tools_by_change(db, [change.id])).get(change.id, []))


async def tonnage_by_change(db: AsyncSession, change_ids: Iterable[int]) -> dict[int, float]:
    """{change id: its tonnage} for the changes that have one (the P&L)."""
    out = {}
    for cid, tools in (await tools_by_change(db, change_ids)).items():
        t = change_tonnage_of(tools).tonnage
        if t is not None:
            out[cid] = t
    return out


# ---------------------------------------------------------------- sync

def sources_status() -> dict:
    """Which sources the sync can ask (never a token, only the host)."""
    return {"machinedb": machinedb_client.config_status(),
            "twos": twos_client.config_status()}


class _RowIndex:
    """The source rows by exact spelling and by number_key; of two rows for
    one key the one with a tonnage (else the first)."""

    def __init__(self, rows, tonnage_of):
        self.exact: dict = {}
        self.folded: dict = {}
        for r in rows:
            for idx, k in ((self.exact, exact_key(r.tool_number)),
                           (self.folded, number_key(r.tool_number))):
                if not k:
                    continue
                if k not in idx or (tonnage_of(idx[k]) is None and tonnage_of(r) is not None):
                    idx[k] = r

    def get(self, number: str):
        """The row spelled exactly like the tool, else (a short all-digit
        number only) the row whose number differs by leading zeros."""
        row = self.exact.get(exact_key(number))
        if row is not None:
            return row
        k = number_key(number)
        return self.folded.get(k) if k is not None else None


def _index(rows, key_of) -> _RowIndex:
    return _RowIndex(rows, key_of)


async def sync_tools(db: AsyncSession, tools: list[Part], *,
                     mdb_rows: Optional[list] = None, twos_rows: Optional[list] = None,
                     now: Optional[datetime] = None, fresh: bool = False) -> dict:
    """Refresh the tonnage of these tool parts from MachineDB and TWOS.

    `mdb_rows` (ImToolDTOs) and `twos_rows` (TwosToolDTOs) replace the HTTP
    calls in tests. A source is asked only when configured (or given); one
    that fails is reported and leaves its stored values alone, so does a
    tool it has no tonnage for. `fresh` bypasses the TWOS client's cache
    (a manual Refresh). Never raises for a source failure. Report:
    {tools, machinedb: {status, matched, updated, no_tonnage, error},
    twos: {...}, without: [tool numbers with no tonnage from any source]}."""
    now = now or datetime.utcnow()
    tools = [t for t in tools if t.item_category == "tool" and (t.part_number or "").strip()]
    report: dict = {"tools": len(tools)}

    # MachineDB
    rep = {"status": "not_configured", "matched": 0, "updated": 0, "no_tonnage": [],
           "error": None}
    if tools and (mdb_rows is not None or machinedb_client.is_configured()):
        try:
            if mdb_rows is None:
                asked = sorted({s for t in tools for s in spellings(t.part_number)})
                mdb_rows = await machinedb_client.list_im_tools(asked)
            idx = _index(mdb_rows, lambda r: r.tonnage_t[0])
            rep["status"] = "ok"
            for t in tools:
                row = idx.get(t.part_number)
                if row is None:
                    continue
                rep["matched"] += 1
                tonnage, basis = row.tonnage_t
                if tonnage is None:
                    rep["no_tonnage"].append(t.part_number)
                    continue
                machine = row.assigned_machine_name if basis == "assigned" else None
                if (t.tool_tonnage_mdb_t, t.tool_tonnage_mdb_basis,
                        t.tool_tonnage_mdb_machine) != (tonnage, basis, machine):
                    rep["updated"] += 1
                t.tool_tonnage_mdb_t, t.tool_tonnage_mdb_basis = tonnage, basis
                t.tool_tonnage_mdb_machine, t.tool_tonnage_mdb_at = machine, now
        except machinedb_client.MachineDBUnavailable as e:
            rep.update(status="failed", error=str(e))
    elif not tools:
        rep["status"] = "no_tools"
    report["machinedb"] = rep

    # TWOS
    rep = {"status": "not_configured", "matched": 0, "updated": 0, "no_tonnage": [],
           "error": None}
    if tools and (twos_rows is not None or twos_client.is_configured()):
        try:
            if twos_rows is None:
                twos_rows = await twos_client.list_tools(fresh=fresh)
            idx = _index(twos_rows, lambda r: r.press_t)
            rep["status"] = "ok"
            for t in tools:
                row = idx.get(t.part_number)
                if row is None:
                    continue
                rep["matched"] += 1
                if row.press_t is None:            # "0" / "": TWOS does not know
                    rep["no_tonnage"].append(t.part_number)
                    continue
                if t.tool_tonnage_twos_t != row.press_t:
                    rep["updated"] += 1
                t.tool_tonnage_twos_t, t.tool_tonnage_twos_at = row.press_t, now
        except twos_client.TwosUnavailable as e:
            rep.update(status="failed", error=str(e))
    elif not tools:
        rep["status"] = "no_tools"
    report["twos"] = rep

    if tools:
        await db.flush()
    report["without"] = [t.part_number for t in tools if tool_tonnage(t) is None]
    return report


async def org_tools(db: AsyncSession, org_id: int) -> list[Part]:
    """Every tool part in the organisation's projects."""
    from app.models.entities import Plant, Project
    return list((await db.execute(
        select(Part).join(Project, Project.id == Part.project_id)
        .join(Plant, Plant.id == Project.plant_id)
        .where(Plant.organization_id == org_id, Part.item_category == "tool")
        .order_by(Part.part_number))).scalars().all())


async def sync_org(db: AsyncSession, org_id: int, **kw) -> dict:
    return await sync_tools(db, await org_tools(db, org_id), **kw)


async def sync_change(db: AsyncSession, change, **kw) -> dict:
    """Refresh the tools of one change (cheap: a handful of tools)."""
    tools = (await tools_by_change(db, [change.id])).get(change.id, [])
    return await sync_tools(db, tools, **kw)


def any_source_configured() -> bool:
    return machinedb_client.is_configured() or twos_client.is_configured()


async def refresh_change_in_background(change_id: int) -> None:
    """After a change's impacted items changed: refresh its tools in a
    session of its own. Best effort; never raises; does nothing when no
    source is configured."""
    if not any_source_configured():
        return
    try:
        from app.models import AsyncSessionLocal
        from app.models.change import ChangeRequest
        async with AsyncSessionLocal() as db:
            change = await db.get(ChangeRequest, change_id)
            if change is None:
                return
            await sync_change(db, change)
            await db.commit()
    except Exception as e:  # noqa: BLE001 - a background refresh never fails a request
        logger.warning("Tool tonnage refresh for change %s failed: %s", change_id,
                       type(e).__name__)


async def sync_on_startup() -> None:
    """Best effort, in the background: one refresh per organisation the
    MachineDB startup sync would touch (startup_sync_orgs), when a source is
    configured and TOOL_TONNAGE_SYNC_ON_STARTUP is not 0. Never raises."""
    if not any_source_configured():
        return
    if (os.getenv("TOOL_TONNAGE_SYNC_ON_STARTUP") or "1").strip().lower() in ("0", "false", "no"):
        return
    from app.models import AsyncSessionLocal
    from app.services.cost_sheet_machines_service import startup_sync_orgs
    try:
        async with AsyncSessionLocal() as db:
            orgs = await startup_sync_orgs(db)
        for org_id in orgs:
            async with AsyncSessionLocal() as db:
                res = await sync_org(db, org_id)
                await db.commit()
            logger.info("Tool tonnage sync org %s: %s tools; MachineDB %s (%s updated); "
                        "TWOS %s (%s updated); %s without a tonnage", org_id, res["tools"],
                        res["machinedb"]["status"], res["machinedb"]["updated"],
                        res["twos"]["status"], res["twos"]["updated"], len(res["without"]))
    except Exception as e:  # noqa: BLE001 - never block or crash startup
        logger.warning("Tool tonnage startup sync skipped: %s", type(e).__name__)
