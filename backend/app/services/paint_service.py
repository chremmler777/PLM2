"""Paint catalog (org-scoped master data) and the per-article paint setup.

A paint belongs to an organization; every query here is scoped by it. A part's
setup hangs off the part (not the revision) and is replaced wholesale on put,
with the layers renumbered 1..n in list order and one changelog line written.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Project
from app.models.paint import Paint, PartPaint, PartPaintLayer
from app.models.part import Part
from app.services.part_service import ChangelogService

EMPTY_SETUP: dict[str, Any] = {
    "paint_required": False,
    "process": None,
    "notes": None,
    "layers": [],
}


class DuplicatePaint(ValueError):
    """A paint with that name already exists in the organization."""


def _paint_dict(paint: Paint) -> dict[str, Any]:
    return {
        "id": paint.id,
        "name": paint.name,
        "paint_type": paint.paint_type,
        "colour_code": paint.colour_code,
        "colour_name": paint.colour_name,
        "colour_hex": paint.colour_hex,
        "supplier_id": paint.supplier_id,
        "supplier_text": paint.supplier_text,
        "spec_reference": paint.spec_reference,
        "notes": paint.notes,
        "is_active": paint.is_active,
    }


def _layer_dict(layer: PartPaintLayer) -> dict[str, Any]:
    return {
        "layer_order": layer.layer_order,
        "area": layer.area,
        "notes": layer.notes,
        "paint": _paint_dict(layer.paint),
    }


def _setup_dict(setup: PartPaint) -> dict[str, Any]:
    return {
        "paint_required": bool(setup.paint_required),
        "process": setup.process,
        "notes": setup.notes,
        "layers": [_layer_dict(ly) for ly in sorted(setup.layers, key=lambda ly: ly.layer_order)],
    }


def _describe(paint_required: bool, process: Optional[str], paints: list[Paint]) -> str:
    """"Paint required · spray · RAL 9005 base (basecoat) → 2K clear (clearcoat)"."""
    if not paint_required:
        return "Paint not required"
    bits = ["Paint required"]
    if process:
        bits.append(process)
    if paints:
        bits.append(" → ".join(f"{p.name} ({p.paint_type})" for p in paints))
    return " · ".join(bits)


class PaintService:
    """Paint master data and article paint setups."""

    # --- catalog -----------------------------------------------------------

    @staticmethod
    async def list_paints(session: AsyncSession, org_id: int, active_only: bool = True,
                          q: Optional[str] = None) -> list[Paint]:
        stmt = select(Paint).where(Paint.organization_id == org_id)
        if active_only:
            stmt = stmt.where(Paint.is_active.is_(True))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Paint.name.ilike(like), Paint.colour_code.ilike(like)))
        stmt = stmt.order_by(Paint.name)
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def get_paint(session: AsyncSession, org_id: int, paint_id: int) -> Paint:
        paint = (await session.execute(
            select(Paint).where(Paint.id == paint_id, Paint.organization_id == org_id)
        )).scalar_one_or_none()
        if paint is None:
            raise ValueError(f"Paint {paint_id} not found in this organization")
        return paint

    @staticmethod
    async def _name_taken(session: AsyncSession, org_id: int, name: str,
                          exclude_id: Optional[int] = None) -> bool:
        stmt = select(Paint.id).where(Paint.organization_id == org_id, Paint.name == name)
        if exclude_id is not None:
            stmt = stmt.where(Paint.id != exclude_id)
        return (await session.execute(stmt)).first() is not None

    @staticmethod
    async def create_paint(session: AsyncSession, org_id: int, created_by: int, **fields) -> Paint:
        name = (fields.pop("name", None) or "").strip()
        if not name:
            raise ValueError("Paint name is required")
        if await PaintService._name_taken(session, org_id, name):
            raise DuplicatePaint(f"A paint named '{name}' already exists")
        fields.pop("organization_id", None)
        fields.pop("created_by", None)
        paint = Paint(organization_id=org_id, name=name, created_by=created_by,
                      **{k: v for k, v in fields.items() if hasattr(Paint, k)})
        if paint.paint_type is None:
            paint.paint_type = "basecoat"
        if paint.is_active is None:
            paint.is_active = True
        session.add(paint)
        await session.flush()
        return paint

    @staticmethod
    async def update_paint(session: AsyncSession, org_id: int, paint_id: int, **fields) -> Paint:
        paint = await PaintService.get_paint(session, org_id, paint_id)
        fields.pop("id", None)
        fields.pop("organization_id", None)
        fields.pop("created_by", None)
        if "name" in fields:
            name = (fields.pop("name") or "").strip()
            if not name:
                raise ValueError("Paint name is required")
            if name != paint.name and await PaintService._name_taken(session, org_id, name, paint.id):
                raise DuplicatePaint(f"A paint named '{name}' already exists")
            paint.name = name
        for key, value in fields.items():
            if hasattr(Paint, key):
                setattr(paint, key, value)
        await session.flush()
        return paint

    @staticmethod
    async def used_in(session: AsyncSession, org_id: int, paint_id: int) -> list[dict]:
        """Articles using the paint, across projects. Empty if not this org's paint."""
        owns = (await session.execute(
            select(Paint.id).where(Paint.id == paint_id, Paint.organization_id == org_id)
        )).first()
        if owns is None:
            return []
        stmt = (
            select(Part.id, Part.part_number, Part.name, Project.id, Project.code,
                   PartPaintLayer.layer_order)
            .join(PartPaint, PartPaintLayer.part_paint_id == PartPaint.id)
            .join(Part, PartPaint.part_id == Part.id)
            .join(Project, Part.project_id == Project.id)
            .where(PartPaintLayer.paint_id == paint_id)
            .order_by(Project.code, Part.part_number, PartPaintLayer.layer_order)
        )
        return [
            {"part_id": pid, "part_number": number, "name": name,
             "project_id": project_id, "project_code": code, "layer_order": order}
            for pid, number, name, project_id, code, order in (await session.execute(stmt)).all()
        ]

    # --- part setup --------------------------------------------------------

    @staticmethod
    async def _setup_for(session: AsyncSession, part_id: int) -> Optional[PartPaint]:
        return (await session.execute(
            select(PartPaint).where(PartPaint.part_id == part_id)
        )).scalar_one_or_none()

    @staticmethod
    async def get_setup(session: AsyncSession, part_id: int) -> dict:
        setup = await PaintService._setup_for(session, part_id)
        if setup is None:
            return dict(EMPTY_SETUP, layers=[])
        return _setup_dict(setup)

    @staticmethod
    async def put_setup(session: AsyncSession, part_id: int, org_id: int, paint_required: bool,
                        process: Optional[str], notes: Optional[str], layers: list[dict],
                        updated_by: int) -> dict:
        """Replace the whole setup; layers are renumbered 1..n in list order."""
        layers = list(layers or [])
        paints: list[Paint] = []
        for entry in layers:
            paint_id = entry.get("paint_id")
            paint = (await session.execute(
                select(Paint).where(Paint.id == paint_id, Paint.organization_id == org_id)
            )).scalar_one_or_none()
            if paint is None:
                raise ValueError(f"Paint {paint_id} does not belong to this organization")
            paints.append(paint)

        setup = await PaintService._setup_for(session, part_id)
        if setup is None:
            setup = PartPaint(part_id=part_id)
            session.add(setup)
        setup.paint_required = bool(paint_required)
        setup.process = process
        setup.notes = notes
        setup.updated_by = updated_by

        await session.flush()  # the setup needs an id before its layers reference it

        # Replace the layers wholesale: the old rows go first so the new 1..n
        # orders cannot collide with them on the (part_paint_id, layer_order) key.
        await session.execute(delete(PartPaintLayer).where(PartPaintLayer.part_paint_id == setup.id))
        for index, (entry, paint) in enumerate(zip(layers, paints), start=1):
            session.add(PartPaintLayer(
                part_paint_id=setup.id, paint_id=paint.id, layer_order=index,
                area=entry.get("area"), notes=entry.get("notes")))
        await session.flush()
        await session.refresh(setup, ["layers"])

        await ChangelogService.log_action(
            session,
            part_id=part_id,
            action="paint_updated",
            action_description=_describe(bool(paint_required), process, paints),
            performed_by=updated_by,
        )
        return _setup_dict(setup)

    # --- overview ----------------------------------------------------------

    @staticmethod
    async def project_overview(session: AsyncSession, project_id: int) -> list[dict]:
        """Every part of the project whose paint is required, with its layers."""
        stmt = (
            select(Part, PartPaint)
            .join(PartPaint, PartPaint.part_id == Part.id)
            .where(Part.project_id == project_id, PartPaint.paint_required.is_(True))
            .order_by(Part.part_number)
        )
        rows = (await session.execute(stmt)).all()
        return [
            {
                "part_id": part.id,
                "part_number": part.part_number,
                "name": part.name,
                "process": setup.process,
                "layers": [_layer_dict(ly) for ly in sorted(setup.layers, key=lambda ly: ly.layer_order)],
            }
            for part, setup in rows
        ]
