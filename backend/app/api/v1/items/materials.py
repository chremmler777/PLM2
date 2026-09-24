"""Material on articles: search MaterialDB through PLM (the service token
stays on the server), link a MaterialDB material, or mark it new."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _part_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.part import Part
from app.schemas.part import PartResponse
from app.services import materialdb_client
from app.services.materialdb_client import MaterialDbUnavailable
from app.services.part_material_service import MaterialGone, PartMaterialService

router = APIRouter(tags=["materials"])


def _unavailable(e: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.get("/materials/search", response_model=List[dict])
async def search_materials(q: str = Query("", max_length=100), current_user: User = Depends(get_current_user)):
    try:
        return await materialdb_client.search(q)
    except MaterialDbUnavailable as e:
        raise _unavailable(e)


class MaterialIn(BaseModel):
    source: Optional[Literal["materialdb", "new"]] = None
    materialdb_id: Optional[int] = None
    new_text: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _shape(self):
        if self.source == "materialdb" and self.materialdb_id is None:
            raise ValueError("materialdb_id is required for a MaterialDB material")
        if self.source == "new" and not (self.new_text or "").strip():
            raise ValueError("Describe the new material")
        return self


async def _article(db: AsyncSession, part_id: int, user: User) -> Part:
    await _part_in_org(db, part_id, user.organization_id)
    return await db.get(Part, part_id)


@router.put("/parts/{part_id}/material", response_model=PartResponse)
async def put_part_material(part_id: int, body: MaterialIn, current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    part = await _article(db, part_id, current_user)
    try:
        if body.source == "materialdb":
            await PartMaterialService.link(db, part, body.materialdb_id, current_user.id)
        elif body.source == "new":
            await PartMaterialService.set_new(db, part, body.new_text, current_user.id)
        else:
            await PartMaterialService.clear(db, part, current_user.id)
    except MaterialDbUnavailable as e:
        await db.rollback()
        raise _unavailable(e)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return part


@router.post("/parts/{part_id}/material/refresh", response_model=PartResponse)
async def refresh_part_material(part_id: int, current_user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    part = await _article(db, part_id, current_user)
    try:
        await PartMaterialService.refresh(db, part, current_user.id)
    except MaterialDbUnavailable as e:
        await db.rollback()
        raise _unavailable(e)
    except MaterialGone as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await db.commit()
    return part
