# backend/app/api/v1/changes/changes.py
"""Change Management endpoints - the change lifecycle spine."""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.services.change_service import ChangeService, ChangeError
from app.schemas.change import (
    ChangeCreate, ChangeUpdate, ChangeResponse, ChangeDetailResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/changes", tags=["changes"])


@router.post("", response_model=ChangeResponse)
async def create_change(
    body: ChangeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        change = await ChangeService.create_change(
            session=db, project_id=body.project_id, title=body.title,
            change_type=body.change_type, raised_by=current_user.id,
            reason=body.reason, description=body.description, priority=body.priority,
            lead_id=body.lead_id, data_classification=body.data_classification,
        )
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(change)
    return change


@router.get("", response_model=List[ChangeResponse])
async def list_changes(
    project_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    lead_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ChangeService.list_changes(
        db, project_id=project_id, status=status, change_type=change_type, lead_id=lead_id,
    )


@router.get("/{change_id}", response_model=ChangeDetailResponse)
async def get_change(
    change_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    change = await ChangeService.get_change(db, change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change
