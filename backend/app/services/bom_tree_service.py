"""BOM follows the revision: copy-forward, multi-level explosion, where-used.

A BOM line points at a child *part*; the tree resolves each child to its
active revision (the newest customer major, or whatever the change engine
last released). Pinning a specific child revision per line is a later
extension, not needed while nominated data is still churning.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.part import Part, PartBOMItem, PartRevision

MAX_DEPTH = 10


class BomTreeService:

    @staticmethod
    async def copy_lines(session: AsyncSession, from_revision_id: int, to_revision_id: int,
                         created_by: Optional[int]) -> int:
        """Copy every BOM line of one revision onto another (same part).
        Returns the number of lines copied."""
        rows = (await session.execute(
            select(PartBOMItem).where(PartBOMItem.revision_id == from_revision_id)
            .order_by(PartBOMItem.position, PartBOMItem.id))).scalars().all()
        for r in rows:
            session.add(PartBOMItem(
                revision_id=to_revision_id, child_part_id=r.child_part_id,
                catalog_part_id=r.catalog_part_id, item_number=r.item_number, name=r.name,
                quantity=r.quantity, unit=r.unit, position=r.position, notes=r.notes,
                created_by=created_by if created_by is not None else r.created_by,
            ))
        if rows:
            await session.flush()
        return len(rows)

    @staticmethod
    async def _display_revision(session: AsyncSession, part: Part) -> Optional[PartRevision]:
        if part.active_revision_id:
            rev = await session.get(PartRevision, part.active_revision_id)
            if rev is not None:
                return rev
        return (await session.execute(
            select(PartRevision)
            .where((PartRevision.part_id == part.id) & (PartRevision.parent_revision_id.is_(None)))
            .order_by(PartRevision.created_at.desc()).limit(1))).scalar_one_or_none()

    @staticmethod
    async def tree(session: AsyncSession, part_id: int, revision_id: Optional[int] = None) -> dict:
        """Explode a part from its active revision (or the given one) down to
        the leaves. Quantities multiply through; a repeated ancestor is marked
        as a cycle and not expanded."""
        part = await session.get(Part, part_id)
        if part is None:
            raise ValueError("Part not found")
        rev = None
        if revision_id is not None:
            rev = await session.get(PartRevision, revision_id)
            if rev is None or rev.part_id != part_id:
                raise ValueError("Revision not found on this part")
        return await BomTreeService._node(session, part, rev, 1.0, 0, set())

    @staticmethod
    async def _node(session: AsyncSession, part: Part, rev: Optional[PartRevision],
                    multiplier: float, depth: int, ancestors: set[int]) -> dict:
        if rev is None:
            rev = await BomTreeService._display_revision(session, part)
        node = {
            "part_id": part.id, "part_number": part.part_number, "name": part.name,
            "part_type": part.part_type, "item_category": part.item_category,
            "revision_id": rev.id if rev else None,
            "revision_name": rev.revision_name if rev else None,
            "revision_phase": rev.phase if rev else None,
            "customer_index": rev.customer_index if rev else None,
            "cycle": part.id in ancestors, "lines": [],
        }
        if node["cycle"] or rev is None or depth >= MAX_DEPTH:
            return node
        items = (await session.execute(
            select(PartBOMItem).where(PartBOMItem.revision_id == rev.id)
            .options(joinedload(PartBOMItem.child_part))
            .order_by(PartBOMItem.position, PartBOMItem.id))).unique().scalars().all()
        next_ancestors = ancestors | {part.id}
        for it in items:
            total = it.quantity * multiplier
            line = {
                "id": it.id, "item_number": it.item_number, "name": it.name,
                "quantity": it.quantity, "unit": it.unit, "total_quantity": total,
                "child_part_id": it.child_part_id, "catalog_part_id": it.catalog_part_id,
                "child": None,
            }
            if it.child_part is not None:
                line["child"] = await BomTreeService._node(
                    session, it.child_part, None, total, depth + 1, next_ancestors)
            node["lines"].append(line)
        return node

    @staticmethod
    async def where_used(session: AsyncSession, part_id: int) -> list[dict]:
        """Every part whose display revision lists this part on its BOM, each
        with its own parents recursively up to the top assemblies."""
        return await BomTreeService._parents(session, part_id, set())

    @staticmethod
    async def _parents(session: AsyncSession, part_id: int, seen: set[int]) -> list[dict]:
        rows = (await session.execute(
            select(PartBOMItem, PartRevision, Part)
            .join(PartRevision, PartRevision.id == PartBOMItem.revision_id)
            .join(Part, Part.id == PartRevision.part_id)
            .where(PartBOMItem.child_part_id == part_id))).all()
        out: list[dict] = []
        done: set[int] = set()
        for item, rev, parent in rows:
            display = await BomTreeService._display_revision(session, parent)
            if display is None or display.id != rev.id or parent.id in done:
                continue
            done.add(parent.id)
            entry = {
                "part_id": parent.id, "part_number": parent.part_number, "name": parent.name,
                "revision_id": rev.id, "revision_name": rev.revision_name,
                "customer_index": rev.customer_index,
                "quantity": item.quantity, "unit": item.unit,
                "parents": [] if parent.id in seen else
                await BomTreeService._parents(session, parent.id, seen | {part_id}),
            }
            out.append(entry)
        return out

    @staticmethod
    async def project_assemblies(session: AsyncSession, project_id: int) -> list[dict]:
        """Top-level assemblies of a project: articles we make ourselves that
        sit on nobody's display-revision BOM. Lines are not required, so a
        freshly nominated panel shows up before its BOM is filled."""
        parts = (await session.execute(
            select(Part).where(Part.project_id == project_id).order_by(Part.part_number))).scalars().all()
        display: dict[int, PartRevision] = {}
        for p in parts:
            rev = await BomTreeService._display_revision(session, p)
            if rev is not None:
                display[p.id] = rev
        rev_ids = [r.id for r in display.values()]
        rows = (await session.execute(
            select(PartBOMItem.revision_id, PartBOMItem.child_part_id)
            .where(PartBOMItem.revision_id.in_(rev_ids)))).all() if rev_ids else []
        line_count: dict[int, int] = {}
        used: set[int] = set()
        for rev_id, child_id in rows:
            line_count[rev_id] = line_count.get(rev_id, 0) + 1
            if child_id is not None:
                used.add(child_id)
        out = []
        for p in parts:
            if p.item_category != "article" or p.part_type == "purchased" or p.id in used:
                continue
            rev = display.get(p.id)
            out.append({
                "part_id": p.id, "part_number": p.part_number, "name": p.name,
                "part_type": p.part_type, "item_category": p.item_category,
                "revision_id": rev.id if rev else None,
                "revision_name": rev.revision_name if rev else None,
                "revision_phase": rev.phase if rev else None,
                "customer_index": rev.customer_index if rev else None,
                "line_count": line_count.get(rev.id, 0) if rev else 0,
            })
        return out

