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


async def _permissions(db, change, user, ctx: dict) -> dict:
    """can_set_machine_class, and can_refresh_tonnage: who may set the
    class, or sync the machines (Sales, Finance, admins)."""
    from app.services import cost_sheet_machines_service as msvc
    ctx["can_set_machine_class"] = await costing_rates.may_set_machine_class(
        db, change, user)
    ctx["can_refresh_tonnage"] = (ctx["can_set_machine_class"]
                                  or await msvc.can_sync(db, user))
    return ctx


@router.get("/{change_id}/costing/context")
async def costing_context(change_id: int, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    change = await _change(db, change_id, current_user)
    return await _permissions(db, change, current_user,
                              await costing_rates.costing_context(db, change))


@router.put("/{change_id}/costing/machine-class")
async def set_machine_class(change_id: int, body: MachineClassIn,
                            current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    change = await _change(db, change_id, current_user)
    if not costing_rates.machine_class_open(change, current_user):
        raise HTTPException(status_code=409,
                            detail="The machine class can only be changed while the "
                                   "change is in costing")
    if not await costing_rates.may_set_machine_class(db, change, current_user):
        raise HTTPException(status_code=403,
                            detail="Only Project Management, an admin or a department "
                                   "costing this change may set its machine class")
    try:
        await costing_rates.set_machine_class(db, change, body.machine_class_id, current_user)
    except costing_rates.MachineClassLocked as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await db.commit()
    return await _permissions(db, change, current_user,
                              await costing_rates.costing_context(db, change))


@router.post("/{change_id}/costing/tool-tonnage/refresh")
async def refresh_tool_tonnage(change_id: int,
                               current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    """Ask MachineDB and TWOS again for the tonnage of this change's tools
    (tool_tonnage_service.sync_change) and answer the costing context with
    the refresh report under "tool_tonnage_refresh". A source that is not
    configured or fails is reported, never an error: the stored tonnage stays.
    Lines already priced keep their class (costing_rates.frozen_tool_class).
    Whoever may set the change's class, or sync the machines (Sales,
    Finance, admins)."""
    from app.services import tool_tonnage_service as tts
    change = await _change(db, change_id, current_user)
    if not (await _permissions(db, change, current_user, {}))["can_refresh_tonnage"]:
        raise HTTPException(status_code=403,
                            detail="Only those who may set this change's machine class, "
                                   "Sales, Finance or an admin may refresh the tool tonnage")
    report = await tts.sync_change(db, change, fresh=True)
    await db.commit()
    ctx = await _permissions(db, change, current_user,
                             await costing_rates.costing_context(db, change))
    ctx["tool_tonnage_refresh"] = report
    return ctx
