"""Rows for the project worksheet: one per article with the producing tool's
values, the active revision, material, paint and the tool's DFM status.
Optional rows: purchased articles and tools that produce no article of the
project. A fixed number of queries regardless of project size."""
from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dfm import DFM_PARTIES, DFM_TOPIC_OPEN, DfmTopic
from app.models.paint import PartPaint
from app.models.part import Part, PartRelation, PartRevision
from app.models.supplier import Supplier
from app.services.dfm_service import flow_state


def material_dict(p: Part) -> dict:
    return {"material_source": p.material_source, "materialdb_id": p.materialdb_id,
            "material_ktx_number": p.material_ktx_number, "material_label": p.material_label,
            "material_new_text": p.material_new_text,
            "material_synced_at": p.material_synced_at.isoformat() if p.material_synced_at else None}


def dfm_status(topics: list, today: Optional[date] = None) -> dict:
    """no_topic | finished (every topic finished confirmed) | waiting (someone
    owes an answer) | all_answered (every open topic answered) | open."""
    if not topics:
        return {"status": "no_topic", "waiting_on": [], "open_topics": 0}
    open_topics = [t for t in topics if t.status == DFM_TOPIC_OPEN]
    if not open_topics:
        return {"status": "finished", "waiting_on": [], "open_topics": 0}
    waiting: set = set()
    all_answered = True
    for t in open_topics:
        flow = flow_state(t, today)
        waiting.update(w["party"] for w in flow["waiting_on"])
        all_answered = all_answered and flow["all_answered"]
    parties = [p for p in DFM_PARTIES if p in waiting]
    status = "waiting" if parties else ("all_answered" if all_answered else "open")
    return {"status": status, "waiting_on": parties, "open_topics": len(open_topics)}


def _paint(setup: Optional[PartPaint]) -> dict:
    if setup is None or not setup.paint_required:
        return {"painted": False, "colour": None, "colour_hex": None, "paint_system": None}
    layers = sorted(setup.layers, key=lambda layer: layer.layer_order)
    top = layers[0].paint if layers else None
    colour = " ".join(x for x in (top.colour_code, top.colour_name) if x) if top else ""
    return {"painted": True, "colour": colour or None, "colour_hex": top.colour_hex if top else None,
            "paint_system": " / ".join(layer.paint.name for layer in layers) or None}


def _tool(t: Part, toolmakers: dict) -> dict:
    return {"part_id": t.id, "part_number": t.part_number, "name": t.name, "cavities": t.tool_cavities,
            "toolmaker_id": t.toolmaker_id, "toolmaker_name": toolmakers.get(t.toolmaker_id),
            "cycle_time_s": t.tool_cycle_time_s, "tonnage_class": t.tool_tonnage_class}


def _identity(p: Part, kind: str) -> dict:
    return {"part_id": p.id, "row_kind": kind, "part_number": p.part_number,
            "customer_part_number": p.customer_part_number, "tier1_part_number": p.tier1_part_number,
            "name": p.name, "part_type": p.part_type, "item_category": p.item_category,
            "thumbnail_url": p.thumbnail_url, "lifecycle_phase": p.lifecycle_phase}


async def worksheet_rows(session: AsyncSession, project_id: int, today: Optional[date] = None) -> dict:
    parts = (await session.execute(
        select(Part).where(Part.project_id == project_id).order_by(Part.part_number))).scalars().all()
    if not parts:
        return {"project_id": project_id, "rows": []}
    by_id = {p.id: p for p in parts}
    articles = [p for p in parts if p.item_category == "article"]
    tools = {p.id: p for p in parts if p.item_category == "tool"}

    rels = (await session.execute(select(PartRelation).where(
        PartRelation.from_part_id.in_(list(by_id)),
        PartRelation.relation_type.in_(("produces", "mirror_of"))))).scalars().all()
    rev_ids = [a.active_revision_id for a in articles if a.active_revision_id]
    revs = {r.id: r for r in (await session.execute(
        select(PartRevision).where(PartRevision.id.in_(rev_ids)))).scalars().all()} if rev_ids else {}
    article_ids = [a.id for a in articles]
    paints = {s.part_id: s for s in (await session.execute(
        select(PartPaint).where(PartPaint.part_id.in_(article_ids)))).scalars().all()} if article_ids else {}
    maker_ids = {t.toolmaker_id for t in tools.values() if t.toolmaker_id}
    toolmakers = dict((await session.execute(
        select(Supplier.id, Supplier.name).where(Supplier.id.in_(maker_ids)))).all()) if maker_ids else {}
    topics_by_tool: dict = defaultdict(list)
    if tools:
        for t in (await session.execute(
                select(DfmTopic).where(DfmTopic.tool_part_id.in_(list(tools))))).scalars().all():
            topics_by_tool[t.tool_part_id].append(t)

    tools_of: dict = defaultdict(list)
    producing: set = set()
    mirror_of: dict = {}
    for r in rels:
        src, dst = by_id.get(r.from_part_id), by_id.get(r.to_part_id)
        if src is None or dst is None:
            continue  # relation into another project
        if r.relation_type == "produces" and src.id in tools and dst.item_category == "article":
            tools_of[dst.id].append(src)
            producing.add(src.id)
        elif r.relation_type == "mirror_of":
            mirror_of[src.id] = {"part_id": dst.id, "part_number": dst.part_number,
                                 "customer_part_number": dst.customer_part_number}

    rows = []
    for a in articles:
        made_by = sorted(tools_of.get(a.id, []), key=lambda t: t.part_number)
        tool = made_by[0] if made_by else None
        rev = revs.get(a.active_revision_id)
        rows.append({
            **_identity(a, "purchased" if a.part_type == "purchased" else "article"),
            "mirror_of": mirror_of.get(a.id),
            "revision": {"revision_name": rev.revision_name, "customer_index": rev.customer_index,
                         "phase": rev.phase.value if hasattr(rev.phase, "value") else rev.phase} if rev else None,
            "material": material_dict(a),
            "paint": _paint(paints.get(a.id)),
            "tool": _tool(tool, toolmakers) if tool else None,
            "other_tools": [t.part_number for t in made_by[1:]],
            "dfm": dfm_status(topics_by_tool.get(tool.id, []), today) if tool else None,
        })
    for t in tools.values():
        if t.id in producing:
            continue
        rows.append({**_identity(t, "tool_only"), "mirror_of": None, "revision": None,
                     "material": material_dict(t), "paint": _paint(None), "tool": _tool(t, toolmakers),
                     "other_tools": [], "dfm": dfm_status(topics_by_tool.get(t.id, []), today)})
    return {"project_id": project_id, "rows": rows}
