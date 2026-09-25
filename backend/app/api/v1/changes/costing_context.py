"""Costing priced from the cost sheet (spec §15 phase 2): the context the
costing table needs (plant, currency, cost sheet version, stale review,
machine classes) and the change's machine class."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services import costing_rates
from app.services.change_service import ChangeService

router = APIRouter(prefix="/changes", tags=["changes"])


class MachineClassIn(BaseModel):
    # None = back to the default from the impacted tool's tonnage
    machine_class_id: Optional[int] = None


async def _change(db, change_id: int, user):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


@router.get("/{change_id}/costing/context")
async def costing_context(change_id: int, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    change = await _change(db, change_id, current_user)
    ctx = await costing_rates.costing_context(db, change)
    ctx["can_set_machine_class"] = await costing_rates.may_set_machine_class(
        db, change, current_user)
    return ctx


@router.put("/{change_id}/costing/machine-class")
async def set_machine_class(change_id: int, body: MachineClassIn,
                            current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    change = await _change(db, change_id, current_user)
    if not await costing_rates.may_set_machine_class(db, change, current_user):
        raise HTTPException(status_code=403,
                            detail="Only Project Management, an admin or a department "
                                   "costing this change may set its machine class")
    try:
        await costing_rates.set_machine_class(db, change, body.machine_class_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await db.commit()
    ctx = await costing_rates.costing_context(db, change)
    ctx["can_set_machine_class"] = True
    return ctx
