"""Tool shrinkage decision record (see app/models/tool_shrink.py).

Candidates come from MaterialDB for the materials of the articles the tool produces:
datasheet values (property with a TDS as source), supplier statements (property whose source
is another document, e.g. a supplier mail) and KTX tool experience (shrinkage experiences of
earlier tools). The engineer picks one or enters an own value, always with a rationale; the
tool's shrinkage fields follow the current decision. After the trial the decision is verified
and reported back to MaterialDB."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Project, User
from app.models.part import Part, PartRelation
from app.models.tool_shrink import ToolShrinkDecision
from app.services import materialdb_client
from app.services.materialdb_client import MaterialDbUnavailable
from app.services.part_service import ChangelogService, PartService

FLOW, CROSS = "shrinkage_flow", "shrinkage_cross"


class ShrinkError(ValueError):
    """Shown to the user (400)."""


def _value(p: Optional[dict]) -> Optional[float]:
    """One number for a property: its value, or the middle of a min-max range."""
    if not p or p.get("value") is None:
        return None
    if p.get("value_max") is None:
        return p["value"]
    return round((p["value"] + p["value_max"]) / 2, 3)


def _range_text(p: Optional[dict]) -> Optional[str]:
    if not p or p.get("value") is None:
        return None
    return f"{p['value']}" if p.get("value_max") is None else f"{p['value']}-{p['value_max']}"


def material_candidates(m: dict) -> list[dict]:
    """Shrinkage candidates of one MaterialDB material (detail payload)."""
    label = materialdb_client.label(m)
    docs = {d["id"]: d for d in m.get("documents") or []}
    by_source: dict = {}
    for p in m.get("properties") or []:
        if p.get("key") in (FLOW, CROSS):
            by_source.setdefault(p.get("source_document_id"), {})[p["key"]] = p
    out = []
    for doc_id, props in by_source.items():
        doc = docs.get(doc_id)
        kind = "datasheet" if doc is None or doc.get("kind") == "tds" else "supplier"
        flow, cross = props.get(FLOW), props.get(CROSS)
        any_p = flow or cross
        if doc:
            src = doc.get("title") or doc.get("filename") or "Document"
            if doc.get("source"):
                src += f" ({doc['source']})"
        else:
            src = "MaterialDB value, no source document"
        out.append({
            "key": f"m{m['id']}-doc{doc_id or 0}", "kind": kind, "materialdb_id": m["id"], "material_label": label,
            "parallel_pct": _value(flow), "normal_pct": _value(cross),
            "parallel_text": _range_text(flow), "normal_text": _range_text(cross),
            "method": any_p.get("test_method"), "condition": any_p.get("condition"),
            "source_label": src, "doc_date": doc.get("doc_date") if doc else None,
            "origin": doc.get("origin") if doc else None,
        })
    for e in m.get("shrink_experiences") or []:
        measured = e.get("measured_flow") is not None or e.get("measured_cross") is not None
        par = e.get("measured_flow") if measured else e.get("planned_flow")
        nor = e.get("measured_cross") if measured else e.get("planned_cross")
        what = "measured" if measured else "steel cut with"
        bits = [f"Tool {e['tool_number']}", e.get("project") and f"project {e['project']}", e.get("article")]
        out.append({
            "key": f"m{m['id']}-exp{e['id']}", "kind": "ktx_experience", "materialdb_id": m["id"],
            "material_label": label, "parallel_pct": par, "normal_pct": nor,
            "parallel_text": None if par is None else str(par), "normal_text": None if nor is None else str(nor),
            "method": what, "condition": e.get("measured_ref") if measured else e.get("planned_source"),
            "source_label": ", ".join(b for b in bits if b) + (f": {e['recommendation']}" if e.get("recommendation") else ""),
            "verdict": e.get("verdict"), "doc_date": (e.get("updated_at") or "")[:10] or None, "origin": None,
        })
    order = {"supplier": 0, "ktx_experience": 1, "datasheet": 2}
    out.sort(key=lambda c: order[c["kind"]])
    return out


async def produced_articles(db: AsyncSession, tool_id: int) -> list[Part]:
    rows = await db.execute(
        select(Part).join(PartRelation, PartRelation.to_part_id == Part.id)
        .where(PartRelation.from_part_id == tool_id, PartRelation.relation_type == "produces")
        .order_by(Part.part_number))
    return list(rows.scalars().unique())


async def candidates(db: AsyncSession, tool: Part) -> dict:
    """{"materials": [...], "candidates": [...], "error": str | None}."""
    articles = await produced_articles(db, tool.id)
    mats, seen = [], set()
    for a in articles:
        if a.material_source == "materialdb" and a.materialdb_id and a.materialdb_id not in seen:
            seen.add(a.materialdb_id)
            mats.append({"materialdb_id": a.materialdb_id, "label": a.material_label, "articles": [a.part_number]})
        elif a.material_source == "materialdb" and a.materialdb_id:
            next(m for m in mats if m["materialdb_id"] == a.materialdb_id)["articles"].append(a.part_number)
    out, error = [], None
    for m in mats:
        try:
            detail = await materialdb_client.fetch_detail(m["materialdb_id"])
        except MaterialDbUnavailable as e:
            error = str(e)
            continue
        m["label"] = materialdb_client.label(detail)
        m["filler_type"] = detail.get("filler_type")
        m["notes"] = detail.get("notes")
        out += material_candidates(detail)
    return {"materials": mats, "candidates": out, "error": error,
            "no_material": not mats and bool(articles), "no_article": not articles}


def to_dict(d: ToolShrinkDecision, names: dict) -> dict:
    return {
        "id": d.id, "status": d.status, "parallel_pct": d.parallel_pct, "normal_pct": d.normal_pct,
        "source_kind": d.source_kind, "source_label": d.source_label, "materialdb_id": d.materialdb_id,
        "material_label": d.material_label, "candidates": d.candidates or [], "rationale": d.rationale,
        "decided_by": names.get(d.decided_by), "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        "measured_parallel_pct": d.measured_parallel_pct, "measured_normal_pct": d.measured_normal_pct,
        "measured_ref": d.measured_ref, "verdict": d.verdict, "next_time_note": d.next_time_note,
        "verified_by": names.get(d.verified_by), "verified_at": d.verified_at.isoformat() if d.verified_at else None,
        "feedback_status": d.feedback_status, "feedback_error": d.feedback_error,
        "feedback_at": d.feedback_at.isoformat() if d.feedback_at else None,
    }


async def history(db: AsyncSession, tool_id: int) -> list[dict]:
    rows = (await db.execute(select(ToolShrinkDecision).where(ToolShrinkDecision.tool_id == tool_id)
                             .order_by(ToolShrinkDecision.decided_at.desc(), ToolShrinkDecision.id.desc()))).scalars().all()
    ids = {i for d in rows for i in (d.decided_by, d.verified_by) if i}
    names = {u.id: u.full_name for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars()} if ids else {}
    return [to_dict(d, names) for d in rows]


async def decide(db: AsyncSession, tool: Part, user: User, *, parallel_pct: float, normal_pct: float,
                 source_kind: str, source_label: Optional[str], rationale: str,
                 materialdb_id: Optional[int], material_label: Optional[str],
                 shown: Optional[list]) -> ToolShrinkDecision:
    if tool.item_category != "tool":
        raise ShrinkError("Shrinkage decisions belong to tools")
    if not (rationale or "").strip():
        raise ShrinkError("Say why this value was chosen")
    if source_kind != "own" and not (source_label or "").strip():
        raise ShrinkError("Name the source of the value")
    for old in (await db.execute(select(ToolShrinkDecision).where(
            ToolShrinkDecision.tool_id == tool.id, ToolShrinkDecision.status == "current"))).scalars():
        old.status = "superseded"
    d = ToolShrinkDecision(
        tool_id=tool.id, status="current", parallel_pct=parallel_pct, normal_pct=normal_pct,
        source_kind=source_kind, source_label=(source_label or "").strip() or None,
        materialdb_id=materialdb_id, material_label=material_label, candidates=shown,
        rationale=rationale.strip(), decided_by=user.id, decided_at=datetime.utcnow())
    db.add(d)
    # The tool's fields follow the decision (logged as field changes like any edit)
    await PartService.update_part(
        session=db, part_id=tool.id, updated_by=user.id,
        tool_shrink_parallel_pct=parallel_pct, update_tool_shrink_parallel_pct=True,
        tool_shrink_normal_pct=normal_pct, update_tool_shrink_normal_pct=True)
    await db.flush()
    await ChangelogService.log_action(
        db, part_id=tool.id, action="shrink_decided", performed_by=user.id,
        action_description=f"Shrinkage {parallel_pct} / {normal_pct} % from {source_kind}"
                           f"{': ' + d.source_label if d.source_label else ''}",
        notes=d.rationale)
    return d


async def _current(db: AsyncSession, tool_id: int, decision_id: int) -> ToolShrinkDecision:
    d = await db.get(ToolShrinkDecision, decision_id)
    if d is None or d.tool_id != tool_id:
        raise LookupError("Decision not found")
    return d


async def verify(db: AsyncSession, tool: Part, decision_id: int, user: User, *,
                 measured_parallel_pct: Optional[float], measured_normal_pct: Optional[float],
                 measured_ref: str, verdict: str, next_time_note: Optional[str]) -> ToolShrinkDecision:
    d = await _current(db, tool.id, decision_id)
    if measured_parallel_pct is None and measured_normal_pct is None:
        raise ShrinkError("Enter the measured shrinkage")
    if not (measured_ref or "").strip():
        raise ShrinkError("Name the measurement (e.g. TH1 6-pc CMM report)")
    if verdict != "correct" and not (next_time_note or "").strip():
        raise ShrinkError("Say what the next tool should use")
    d.measured_parallel_pct, d.measured_normal_pct = measured_parallel_pct, measured_normal_pct
    d.measured_ref, d.verdict = measured_ref.strip(), verdict
    d.next_time_note = (next_time_note or "").strip() or None
    d.verified_by, d.verified_at = user.id, datetime.utcnow()
    await db.flush()
    await ChangelogService.log_action(
        db, part_id=tool.id, action="shrink_verified", performed_by=user.id,
        action_description=f"Shrinkage verified: {verdict} (measured {measured_parallel_pct} / "
                           f"{measured_normal_pct} %, {d.measured_ref})", notes=d.next_time_note)
    await report(db, tool, d, user)
    return d


async def report(db: AsyncSession, tool: Part, d: ToolShrinkDecision, user: User) -> None:
    """Send the verified decision to MaterialDB; the outcome is stored, never raised."""
    d.feedback_at = datetime.utcnow()
    if not d.materialdb_id:
        d.feedback_status, d.feedback_error = "skipped", "No MaterialDB material on this decision"
        return
    articles = await produced_articles(db, tool.id)
    project = await db.get(Project, tool.project_id)
    planned_source = f"{d.source_kind}: {d.source_label}" if d.source_label else d.source_kind
    body = {
        "material_id": d.materialdb_id, "tool_number": tool.part_number,
        "article": ", ".join(f"{a.part_number} {a.name}" for a in articles)[:300] or None,
        "project": (project.code if project else None),
        "planned_flow": d.parallel_pct, "planned_cross": d.normal_pct,
        "planned_source": f"{planned_source}\nWhy: {d.rationale}"[:2000],
        "measured_flow": d.measured_parallel_pct, "measured_cross": d.measured_normal_pct,
        "measured_ref": d.measured_ref, "verdict": d.verdict,
        "recommendation": d.next_time_note or f"Keep {d.parallel_pct} / {d.normal_pct} %",
        "source": f"PLM2 tool {tool.part_number}, shrinkage decision {d.id}",
        "actor": user.full_name or user.username,
    }
    try:
        await materialdb_client.put_shrink_experience(d.id, body)
        d.feedback_status, d.feedback_error = "sent", None
    except MaterialDbUnavailable as e:
        d.feedback_status, d.feedback_error = "failed", str(e)[:500]
    await db.flush()


async def resend(db: AsyncSession, tool: Part, decision_id: int, user: User) -> ToolShrinkDecision:
    d = await _current(db, tool.id, decision_id)
    if d.verified_at is None:
        raise ShrinkError("Verify the decision before reporting it")
    await report(db, tool, d, user)
    return d
