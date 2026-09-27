# backend/app/api/v1/changes/mother_plant.py
"""Mother-plant changes (spec 2026-09-25 §14): the Mother plant tab.

    (the configured plants ride on GET /changes/permissions)
    GET  /changes/{id}/mother-plant                 tab state + caller rights
    POST /changes/{id}/mother-plant/info            send information (PM)
    POST /changes/{id}/mother-plant/info/{rid}/ack  read and understood
    POST /changes/{id}/mother-plant/inform          "Inform mother plant" stamp

The service owns every rule: ChangeError -> 400, MotherPlantForbidden ->
403, MotherPlantNotFound -> 404.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services.change_service import ChangeError, ChangeService
from app.services.mother_plant_service import (
    MotherPlantForbidden, MotherPlantNotFound, MotherPlantService,
)

router = APIRouter(prefix="/changes", tags=["changes"])


class InfoSendIn(BaseModel):
    department_ids: List[int] = Field(default_factory=list)
    message: Optional[str] = Field(None, max_length=2000)


class InfoAckIn(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)


def _http(e: Exception) -> HTTPException:
    if isinstance(e, MotherPlantForbidden):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, MotherPlantNotFound):
        return HTTPException(status_code=404, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


_ERRORS = (ChangeError, MotherPlantForbidden, MotherPlantNotFound)


async def _change(db: AsyncSession, change_id: int, user: User):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


@router.get("/{change_id}/mother-plant")
async def get_mother_plant(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        return await MotherPlantService.state(db, change, current_user)
    except _ERRORS as e:
        raise _http(e)


@router.post("/{change_id}/mother-plant/info")
async def send_info(
    change_id: int, body: InfoSendIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await MotherPlantService.send_info(
            db, change, body.department_ids, current_user, body.message)
        await db.commit()
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    await db.refresh(change)
    return await MotherPlantService.state(db, change, current_user)


@router.post("/{change_id}/mother-plant/info/{receipt_id}/ack")
async def acknowledge_info(
    change_id: int, receipt_id: int, body: InfoAckIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await MotherPlantService.acknowledge(
            db, change, receipt_id, current_user, body.note)
        await db.commit()
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    await db.refresh(change)
    return await MotherPlantService.state(db, change, current_user)


@router.post("/{change_id}/mother-plant/inform")
async def inform_mother_plant(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await MotherPlantService.inform_timing(db, change, current_user)
        await db.commit()
    except _ERRORS as e:
        await db.rollback()
        raise _http(e)
    await db.refresh(change)
    return await MotherPlantService.state(db, change, current_user)
