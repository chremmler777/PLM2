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
from app.services.equipment_numbering import (
    TOOL_WIDTH, classify, parse_equipment_number)


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
    async def find_tool(session: AsyncSession, tool_number: str) -> Optional[Part]:
        """Tool part by number. Sheets write '745' where the PLM stores '0745',
        so a short all-digit number is retried zero-padded."""
        candidates = [tool_number]
        if tool_number.isdigit() and len(tool_number) < TOOL_WIDTH:
            candidates.append(tool_number.zfill(TOOL_WIDTH))
        return (await session.execute(
            select(Part).where(Part.item_category == "tool",
                               Part.part_number.in_(candidates))
            .order_by(Part.part_number))).scalars().first()

    @staticmethod
    async def stations_for(session: AsyncSession, tool: Part,
                           include_gauges: bool = True) -> list[dict]:
        """Equipment serving this tool, ordered mold -> in-cell -> secondary
        -> gauge. The relation, not the number, is authoritative: 3455's
        station is numbered 3454-30."""
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
            kind = classify(op_code)
            if kind == "gauge" and not include_gauges:
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
                "kind": kind,
                "serves": list(covered),
            })
        stations.sort(key=lambda s: (s["op_code"], s["part_number"]))
        return stations

    @staticmethod
    async def build(session: AsyncSession, part_id: int) -> Optional[dict]:
        part = await session.get(Part, part_id)
        if part is None:
            return None
        tool = await ProcessFlowService._resolve_tool(session, part)
        if tool is None:
            return {"tool": _part_brief(part), "upstream": [], "downstream": [],
                    "stations": []}

        stations = await ProcessFlowService.stations_for(session, tool)

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
