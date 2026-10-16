"""Moldflow timing rows: the project overview (rows with tool and produced
articles), the worksheet cell (latest version per tool), the derived status
and the writes with their audit entries."""
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.moldflow import MF_DATES, MF_INPUTS, ToolMoldflow
from app.models.part import Part, PartRelation
from app.services.audit_service import AuditService

ENTITY = "tool_moldflow"
EDITABLE = (
    "version", "cavity_layout", *MF_INPUTS, "material_label", "udb_source",
    *(c for c, _ in MF_DATES), "customer_feedback", "status", "blockers", "owner", "notes", "source_ref",
)
STATUS_LABELS = {
    "not_started": "Not started", "inputs_open": "Inputs open", "ready_for_mf": "Ready for MF",
    "running": "MF running", "received": "Received", "in_review": "KTX review",
    "sent_to_customer": "At customer", "customer_feedback": "Customer feedback", "rework": "Rework",
    "final": "Final",
}


class MoldflowError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def version_number(v: Optional[str]) -> int:
    m = re.search(r"\d+", v or "")
    return int(m.group()) if m else 0


def derive_status(row) -> str:
    """The status the recorded dates and inputs point to (latest step wins).
    Rework is never derived: it is a decision, set by hand."""
    if row.final_on:
        return "final"
    if row.customer_feedback_on:
        return "customer_feedback"
    if row.sent_customer_on:
        return "sent_to_customer"
    if row.ktx_review_on:
        return "in_review"
    if row.received_on:
        return "received"
    if row.mf_requested_on:
        return "running"
    inputs = [getattr(row, k) or "open" for k in MF_INPUTS]
    if all(s in ("ready", "n/a") for s in inputs):
        return "ready_for_mf"
    if all(s == "open" for s in inputs) and not row.material_label:
        return "not_started"
    return "inputs_open"


def last_step(row) -> Optional[dict]:
    """The latest recorded step date: {key, label, on}."""
    for col, label in reversed(MF_DATES):
        d = getattr(row, col)
        if d:
            return {"key": col, "label": label, "on": d.isoformat()}
    return None


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def row_dict(r: ToolMoldflow) -> dict:
    return {
        "id": r.id, "tool_part_id": r.tool_part_id, "version": r.version, "cavity_layout": r.cavity_layout,
        **{k: getattr(r, k) for k in MF_INPUTS},
        "material_label": r.material_label, "udb_source": r.udb_source,
        **{c: _iso(getattr(r, c)) for c, _ in MF_DATES},
        "customer_feedback": r.customer_feedback, "status": r.status, "derived_status": derive_status(r),
        "blockers": r.blockers, "owner": r.owner, "notes": r.notes, "source_ref": r.source_ref,
        "created_at": _iso(r.created_at), "created_by": r.created_by,
        "updated_at": _iso(r.updated_at), "updated_by": r.updated_by,
    }


def _sort_key(r: ToolMoldflow):
    return (version_number(r.version), r.cavity_layout or "", r.id)


def latest(rows: Iterable[ToolMoldflow]) -> Optional[ToolMoldflow]:
    """The tool's row of the highest version; among layouts of that version the
    one changed last."""
    rows = list(rows)
    if not rows:
        return None
    top = max(version_number(r.version) for r in rows)
    same = [r for r in rows if version_number(r.version) == top]
    return max(same, key=lambda r: (r.updated_at or datetime.min, r.id))


def worksheet_cell(rows: list) -> Optional[dict]:
    """The worksheet's Moldflow cell for one tool; None: no Moldflow row yet."""
    r = latest(rows)
    if r is None:
        return None
    layouts = sum(1 for x in rows if version_number(x.version) == version_number(r.version))
    return {"id": r.id, "version": r.version, "cavity_layout": r.cavity_layout, "layouts": layouts,
            "status": r.status, "last_step": last_step(r), "blockers": r.blockers,
            "versions": len({x.version for x in rows})}


async def rows_by_tool(session: AsyncSession, tool_ids: Iterable[int]) -> dict[int, list]:
    ids = list(tool_ids)
    out: dict = defaultdict(list)
    if not ids:
        return out
    for r in (await session.execute(select(ToolMoldflow).where(
            ToolMoldflow.tool_part_id.in_(ids), ToolMoldflow.deleted_at.is_(None)))).scalars():
        out[r.tool_part_id].append(r)
    return out


async def project_overview(session: AsyncSession, project_id: int) -> list[dict]:
    """Every tool of the project (with or without Moldflow rows), its produced
    articles' identities and its rows, by tool number then version."""
    tools = (await session.execute(select(Part).where(
        Part.project_id == project_id, Part.item_category == "tool").order_by(Part.part_number))).scalars().all()
    if not tools:
        return []
    tool_ids = [t.id for t in tools]
    produced = (await session.execute(
        select(PartRelation.from_part_id, Part)
        .join(Part, Part.id == PartRelation.to_part_id)
        .where(PartRelation.from_part_id.in_(tool_ids), PartRelation.relation_type == "produces",
               Part.item_category == "article"))).all()
    articles: dict = defaultdict(list)
    for tool_id, a in produced:
        articles[tool_id].append({"part_id": a.id, "part_number": a.part_number,
                                  "customer_part_number": a.customer_part_number,
                                  "tier1_part_number": a.tier1_part_number, "name": a.name})
    by_tool = await rows_by_tool(session, tool_ids)
    out = []
    for t in tools:
        rows = sorted(by_tool.get(t.id, []), key=_sort_key)
        out.append({
            "tool": {"part_id": t.id, "part_number": t.part_number, "name": t.name, "cavities": t.tool_cavities},
            "articles": sorted(articles.get(t.id, []), key=lambda a: a["customer_part_number"] or a["part_number"]),
            "rows": [row_dict(r) for r in rows],
            "latest_id": (latest(rows).id if rows else None),
        })
    return out


def _clean(field: str, value):
    if isinstance(value, str):
        value = value.strip()
        if value == "" and field not in ("version",):
            return None
    return value


async def _duplicate(session: AsyncSession, tool_id: int, version: str, layout: Optional[str],
                     exclude_id: Optional[int] = None) -> bool:
    q = select(ToolMoldflow.id).where(
        ToolMoldflow.tool_part_id == tool_id, ToolMoldflow.version == version,
        func.coalesce(ToolMoldflow.cavity_layout, "") == (layout or ""), ToolMoldflow.deleted_at.is_(None))
    if exclude_id is not None:
        q = q.where(ToolMoldflow.id != exclude_id)
    return (await session.execute(q)).first() is not None


DUPLICATE = "This tool already has a Moldflow row for that version and cavity layout"


async def create(session: AsyncSession, tool: Part, data: dict, user_id: Optional[int]) -> ToolMoldflow:
    if tool.item_category != "tool":
        raise MoldflowError("Moldflow rows belong to tools")
    values = {k: _clean(k, v) for k, v in data.items() if k in EDITABLE}
    values["version"] = (values.get("version") or "V1").upper()
    if await _duplicate(session, tool.id, values["version"], values.get("cavity_layout")):
        raise MoldflowError(DUPLICATE, 409)
    row = ToolMoldflow(tool_part_id=tool.id, created_by=user_id, updated_by=user_id,
                       **{k: v for k, v in values.items() if v is not None})
    if not values.get("status"):
        row.status = derive_status(row)
    session.add(row)
    await session.flush()
    await AuditService.record(session, entity_type=ENTITY, entity_id=row.id, action="moldflow_created",
                              user_id=user_id, new_values={"tool": tool.part_number, **row_dict(row)})
    return row


async def update(session: AsyncSession, row: ToolMoldflow, data: dict, user_id: Optional[int]) -> ToolMoldflow:
    old, new = {}, {}
    for k, v in data.items():
        if k not in EDITABLE:
            continue
        v = _clean(k, v)
        if k == "version":
            if not v:
                raise MoldflowError("version must not be blank")
            v = v.upper()
        if k in MF_INPUTS and v is None:
            v = "open"
        if k == "status" and v is None:
            raise MoldflowError("status must not be blank")
        if _iso(getattr(row, k)) != _iso(v):
            old[k], new[k] = _iso(getattr(row, k)), v
    if not new:
        return row
    if ("version" in new or "cavity_layout" in new) and await _duplicate(
            session, row.tool_part_id, new.get("version", row.version),
            new["cavity_layout"] if "cavity_layout" in new else row.cavity_layout, exclude_id=row.id):
        raise MoldflowError(DUPLICATE, 409)
    for k, v in new.items():
        setattr(row, k, v)
    new = {k: _iso(v) for k, v in new.items()}
    row.updated_by = user_id
    row.updated_at = datetime.utcnow()
    await session.flush()
    await AuditService.record(session, entity_type=ENTITY, entity_id=row.id, action="moldflow_updated",
                              user_id=user_id, old_values=old, new_values=new)
    return row


async def soft_delete(session: AsyncSession, row: ToolMoldflow, user_id: Optional[int]) -> None:
    row.deleted_at = datetime.utcnow()
    row.deleted_by = user_id
    await session.flush()
    await AuditService.record(session, entity_type=ENTITY, entity_id=row.id, action="moldflow_deleted",
                              user_id=user_id, old_values=row_dict(row))
