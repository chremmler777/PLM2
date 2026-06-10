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
from app.services.part_service import PartService, ChangelogService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parts", tags=["part-relations"])

VALID_RELATION_TYPES = {"produces", "checks", "assembles", "related"}

# Human-readable labels per direction
RELATION_LABELS = {
    "produces": ("produces", "produced by"),
    "checks": ("checks", "checked by"),
    "assembles": ("assembles", "assembled by"),
    "related": ("related to", "related to"),
}


class RelationCreate(BaseModel):
    to_part_id: int
    relation_type: str = Field(..., description="produces, checks, assembles, related")
    notes: Optional[str] = None


def _relation_dict(rel: PartRelation, direction: str) -> dict:
    other = rel.to_part if direction == "outgoing" else rel.from_part
    forward, backward = RELATION_LABELS.get(rel.relation_type, (rel.relation_type, rel.relation_type))
    return {
        "id": rel.id,
        "relation_type": rel.relation_type,
        "direction": direction,
        "label": forward if direction == "outgoing" else backward,
        "other_part_id": other.id,
        "other_part_number": other.part_number,
        "other_part_name": other.name,
        "other_item_category": other.item_category,
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
        if from_part.project_id != to_part.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Related parts must be in the same project",
            )

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
            created_by=current_user.id,
        )
        db.add(rel)
        await db.flush()

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
            .options(joinedload(PartRelation.from_part))
        )
        rel = result.unique().scalar_one_or_none()
        if not rel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found")

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
