"""Derive a tool's process route from serves/feeds relations.

Nothing is stored: the flow is whatever the equipment records currently say, so
it cannot drift from them. The cost is that an ordering not implied by op code
(two secondary stations in a required sequence) cannot be expressed.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.part import Part, PartRelation
from app.services.equipment_numbering import classify, parse_equipment_number


def _part_brief(part: Part) -> dict:
    return {"id": part.id, "part_number": part.part_number, "name": part.name}


class ProcessFlowService:

    @staticmethod
    async def _resolve_tool(session: AsyncSession, part: Part) -> Optional[Part]:
        """Equipment resolves to the tool it serves; a tool resolves to itself.

        Uses the serves relation rather than the number, because the number only
        names the lowest tool a shared station covers.
        """
        if part.item_category == "tool":
            return part
        return (await session.execute(
            select(Part).join(PartRelation, PartRelation.to_part_id == Part.id)
            .where(PartRelation.from_part_id == part.id,
                   PartRelation.relation_type == "serves")
            .order_by(Part.part_number))).scalars().first()

    @staticmethod
    async def build(session: AsyncSession, part_id: int) -> Optional[dict]:
        part = await session.get(Part, part_id)
        if part is None:
            return None
        tool = await ProcessFlowService._resolve_tool(session, part)
        if tool is None:
            return {"tool": _part_brief(part), "upstream": [], "downstream": [],
                    "stations": []}

        # Equipment that serves this tool — the relation, not the number, is
        # authoritative: 3455's station is numbered 3454-30.
        station_rows = (await session.execute(
            select(PartRelation)
            .where(PartRelation.to_part_id == tool.id,
                   PartRelation.relation_type == "serves")
            .options(joinedload(PartRelation.from_part)))).scalars().all()

        stations = []
        for rel in station_rows:
            equipment = rel.from_part
            _, op_code = parse_equipment_number(equipment.part_number)
            if op_code is None:
                continue
            covered = (await session.execute(
                select(Part.part_number).join(
                    PartRelation, PartRelation.to_part_id == Part.id)
                .where(PartRelation.from_part_id == equipment.id,
                       PartRelation.relation_type == "serves")
                .order_by(Part.part_number))).scalars().all()
            stations.append({
                "id": equipment.id,
                "part_number": equipment.part_number,
                "name": equipment.name,
                "op_code": op_code,
                "kind": classify(op_code),
                "serves": list(covered),
            })
        stations.sort(key=lambda s: (s["op_code"], s["part_number"]))

        upstream = [
            {**_part_brief(rel.from_part), "note": rel.notes}
            for rel in (await session.execute(
                select(PartRelation)
                .where(PartRelation.to_part_id == tool.id,
                       PartRelation.relation_type == "feeds")
                .options(joinedload(PartRelation.from_part)))).scalars().all()
        ]
        downstream = [
            {**_part_brief(rel.to_part), "note": rel.notes}
            for rel in (await session.execute(
                select(PartRelation)
                .where(PartRelation.from_part_id == tool.id,
                       PartRelation.relation_type == "feeds")
                .options(joinedload(PartRelation.to_part)))).scalars().all()
        ]

        return {"tool": _part_brief(tool), "upstream": upstream,
                "downstream": downstream, "stations": stations}
