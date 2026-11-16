"""API endpoints for item relations - linking tools/gauges/equipment to articles."""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload

from app.dependencies import get_current_user
from app.models import get_db, User, PartRelation
from app.services.equipment_rights import require_relation_editor
from app.services import equipment_service
from app.services.equipment_service import EquipmentError
from app.services.part_service import PartService, ChangelogService
from app.services.relation_labels import RELATION_LABELS, VALID_RELATION_TYPES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parts", tags=["part-relations"])


class RelationCreate(BaseModel):
    to_part_id: int
    relation_type: str = Field(..., description="produces, checks, assembles, related")
    notes: Optional[str] = None
    # assembles only: how many of the article the equipment takes in per cycle (default 1)
    quantity: Optional[float] = None


class RelationUpdate(BaseModel):
    quantity: float


def _relation_dict(rel: PartRelation, direction: str) -> dict:
    other = rel.to_part if direction == "outgoing" else rel.from_part
    forward, backward = RELATION_LABELS.get(rel.relation_type, (rel.relation_type, rel.relation_type))
    active = next((r for r in other.revisions if r.id == other.active_revision_id), None)
    return {
        "id": rel.id,
        "relation_type": rel.relation_type,
        "direction": direction,
        "label": forward if direction == "outgoing" else backward,
        "other_part_id": other.id,
        "other_part_number": other.part_number,
        "other_part_name": other.name,
        "other_item_category": other.item_category,
        "other_customer_part_number": other.customer_part_number,
        "other_obsolete_at": other.obsolete_at,
        "quantity": rel.quantity,
        "other_active_revision_name": active.revision_name if active else None,
        "other_active_customer_index": active.customer_index if active else None,
        "notes": rel.notes,
    }


@router.post("/{part_id}/relations", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_relation(
    part_id: int,
    body: RelationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Link this item to another (e.g. tool 'produces' article)."""
    try:
        if body.relation_type not in VALID_RELATION_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid relation_type. Valid: {', '.join(sorted(VALID_RELATION_TYPES))}",
            )
        if body.to_part_id == part_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A part cannot relate to itself",
            )

        from_part = await PartService.get_part(db, part_id)
        to_part = await PartService.get_part(db, body.to_part_id)
        if not from_part or not to_part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
        # produces is tool data, checks gauge data, assembles equipment data, serves the from-item's
        await require_relation_editor(db, current_user, body.relation_type, from_part.item_category)
        if from_part.project_id != to_part.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Related parts must be in the same project",
            )
        # Obsolete gauges and equipment take no new links; an amount belongs to assembles only
        quantity = None
        try:
            equipment_service.require_active(from_part, to_part)
            if body.relation_type == "assembles":
                quantity = 1 if body.quantity is None else body.quantity
                if quantity <= 0:
                    raise EquipmentError(equipment_service.QUANTITY_INVALID)
        except EquipmentError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        if body.relation_type == "mirror_of":
            if from_part.item_category != "article" or to_part.item_category != "article":
                raise HTTPException(status_code=400, detail="Only articles can be mirrors of articles")
            already = await db.execute(select(PartRelation).where(
                PartRelation.from_part_id == part_id, PartRelation.relation_type == "mirror_of").limit(1))
            if already.scalars().first():
                raise HTTPException(status_code=409, detail="This part is already a mirror of another part")
            source_is_mirror = await db.execute(select(PartRelation).where(
                PartRelation.from_part_id == body.to_part_id, PartRelation.relation_type == "mirror_of").limit(1))
            if source_is_mirror.scalars().first():
                raise HTTPException(status_code=400, detail="The source part is itself a mirror; point at the part that holds the data")
            is_mirrored_by_others = await db.execute(select(PartRelation).where(
                PartRelation.to_part_id == part_id, PartRelation.relation_type == "mirror_of").limit(1))
            if is_mirrored_by_others.scalars().first():
                raise HTTPException(status_code=400, detail="Other parts mirror this one; it must hold the data")

        existing = await db.execute(
            select(PartRelation).where(
                PartRelation.from_part_id == part_id,
                PartRelation.to_part_id == body.to_part_id,
                PartRelation.relation_type == body.relation_type,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This relation already exists",
            )

        rel = PartRelation(
            from_part_id=part_id,
            to_part_id=body.to_part_id,
            relation_type=body.relation_type,
            notes=body.notes,
            quantity=quantity,
            created_by=current_user.id,
        )
        db.add(rel)
        await db.flush()
        if equipment_service.is_equipment(from_part) and body.relation_type in equipment_service.EQUIPMENT_RELATIONS:
            # the equipment's own history: "Article 50-2277-001-0 added, quantity 2"
            await equipment_service.log_link_added(db, from_part, to_part, current_user.id, quantity)

        await ChangelogService.log_action(
            db,
            part_id=body.to_part_id,
            action="relation_added",
            action_description=f"{from_part.item_category} '{from_part.name}' ({from_part.part_number}) {RELATION_LABELS[body.relation_type][0]} this item",
            performed_by=current_user.id,
        )
        await db.commit()

        rel.from_part = from_part
        rel.to_part = to_part
        return _relation_dict(rel, "outgoing")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create relation from part {part_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{part_id}/relations", response_model=List[dict])
async def list_relations(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All relations of this item, both directions, with the other part resolved."""
    part = await PartService.get_part(db, part_id)
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    result = await db.execute(
        select(PartRelation)
        .where(or_(PartRelation.from_part_id == part_id, PartRelation.to_part_id == part_id))
        .options(joinedload(PartRelation.from_part), joinedload(PartRelation.to_part))
        .order_by(PartRelation.relation_type, PartRelation.id)
    )
    relations = result.unique().scalars().all()
    return [
        _relation_dict(rel, "outgoing" if rel.from_part_id == part_id else "incoming")
        for rel in relations
    ]


@router.patch("/relations/{relation_id}", response_model=dict)
async def update_relation(
    relation_id: int,
    body: RelationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the amount of an assembles link (how many of the article the equipment takes
    in). Logged in the equipment's history."""
    rel = (await db.execute(
        select(PartRelation).where(PartRelation.id == relation_id)
        .options(joinedload(PartRelation.from_part), joinedload(PartRelation.to_part))
    )).unique().scalar_one_or_none()
    if not rel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found")
    await require_relation_editor(db, current_user, rel.relation_type, rel.from_part.item_category)
    try:
        if rel.relation_type != "assembles":
            raise EquipmentError(equipment_service.QUANTITY_ONLY_ASSEMBLES)
        if body.quantity <= 0:
            raise EquipmentError(equipment_service.QUANTITY_INVALID)
        equipment_service.require_active(rel.from_part)
    except EquipmentError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    old = rel.quantity
    if old is None or float(old) != float(body.quantity):
        rel.quantity = body.quantity
        await equipment_service.log_quantity_changed(db, rel.from_part, rel.to_part, current_user.id, old, body.quantity)
        await db.commit()
    return _relation_dict(rel, "outgoing")


@router.delete("/relations/{relation_id}")
async def delete_relation(
    relation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an item relation."""
    try:
        result = await db.execute(
            select(PartRelation)
            .where(PartRelation.id == relation_id)
            .options(joinedload(PartRelation.from_part), joinedload(PartRelation.to_part))
        )
        rel = result.unique().scalar_one_or_none()
        if not rel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found")
        await require_relation_editor(db, current_user, rel.relation_type, rel.from_part.item_category)
        owned = equipment_service.is_equipment(rel.from_part) and rel.relation_type in equipment_service.EQUIPMENT_RELATIONS
        if owned:
            try:
                equipment_service.require_active(rel.from_part)
            except EquipmentError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
            await equipment_service.log_link_removed(db, rel.from_part, rel.to_part, current_user.id)

        await ChangelogService.log_action(
            db,
            part_id=rel.to_part_id,
            action="relation_removed",
            action_description=f"Removed link to '{rel.from_part.name}' ({rel.relation_type})",
            performed_by=current_user.id,
        )
        await db.delete(rel)
        await db.commit()
        return {"status": "success", "message": "Relation removed"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete relation {relation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
