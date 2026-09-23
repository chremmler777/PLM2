"""One call for the project page's structure tree: every article with its
revisions, its related tools/gauges/equipment, and its mirror links.
Four queries regardless of project size."""
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.relation_labels import RELATION_LABELS
from app.models.part import Part, PartRelation, PartRevision


def _brief(p: Part) -> dict:
    return {"part_id": p.id, "part_number": p.part_number,
            "customer_part_number": p.customer_part_number, "name": p.name,
            "thumbnail_url": p.thumbnail_url}


async def project_structure(session: AsyncSession, project_id: int) -> dict:
    parts = (await session.execute(
        select(Part).where(Part.project_id == project_id).order_by(Part.part_number))).scalars().all()
    if not parts:
        return {"articles": []}
    by_id = {p.id: p for p in parts}
    article_ids = [p.id for p in parts if p.item_category == "article"]
    revs = (await session.execute(
        select(PartRevision).where(PartRevision.part_id.in_(article_ids))
        .order_by(PartRevision.created_at))).scalars().all()
    rels = (await session.execute(
        select(PartRelation).where(
            (PartRelation.from_part_id.in_(list(by_id))) | (PartRelation.to_part_id.in_(list(by_id))))
        .order_by(PartRelation.relation_type, PartRelation.id))).scalars().all()

    revs_by_part: dict[int, list] = defaultdict(list)
    for r in revs:
        revs_by_part[r.part_id].append(r)
    related: dict[int, list] = defaultdict(list)
    mirror_of: dict[int, dict] = {}
    mirrored_by: dict[int, list] = defaultdict(list)
    for r in rels:
        src, dst = by_id.get(r.from_part_id), by_id.get(r.to_part_id)
        if src is None or dst is None:
            continue  # relation into another project's part: not part of this tree
        if r.relation_type == "mirror_of":
            mirror_of[src.id] = _brief(dst)
            mirrored_by[dst.id].append(_brief(src))
            continue
        fwd, back = RELATION_LABELS.get(r.relation_type, (r.relation_type, r.relation_type))
        related[src.id].append({"relation_type": r.relation_type, "direction": "outgoing", "label": fwd,
                                "part_id": dst.id, "part_number": dst.part_number, "name": dst.name,
                                "item_category": dst.item_category})
        related[dst.id].append({"relation_type": r.relation_type, "direction": "incoming", "label": back,
                                "part_id": src.id, "part_number": src.part_number, "name": src.name,
                                "item_category": src.item_category})

    articles = []
    for p in parts:
        if p.item_category != "article":
            continue
        articles.append({
            **_brief(p), "lifecycle_phase": p.lifecycle_phase, "active_revision_id": p.active_revision_id,
            "revisions": [{
                "id": r.id, "revision_name": r.revision_name, "customer_index": r.customer_index,
                "status": r.status.value if hasattr(r.status, "value") else r.status,
                "phase": r.phase.value if hasattr(r.phase, "value") else r.phase,
                "parent_revision_id": r.parent_revision_id, "is_active": r.id == p.active_revision_id,
            } for r in revs_by_part.get(p.id, [])],
            "related": sorted(related.get(p.id, []), key=lambda x: (x["relation_type"], x["part_number"])),
            "mirror_of": mirror_of.get(p.id),
            "mirrored_by": mirrored_by.get(p.id, []),
        })
    return {"articles": articles}
