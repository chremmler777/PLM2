"""Cost sheet machines API: the MachineDB presses and their per-machine rates.

Read: everyone in the org (like the rest of the sheet). Sync and plant
mapping: Sales, Finance or an admin. Per-machine rates: whoever may edit the
cost sheet (cost_sheet_service.require_edit), in the open draft only.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models.cost_sheet import CURRENCIES
from app.models import get_db, User
from app.services import cost_sheet_machines_service as msvc
from app.services import cost_sheet_service as svc
from app.services import machinedb_client
from app.services.cost_sheet_service import CostSheetError

router = APIRouter(prefix="/cost-sheet/machines", tags=["cost-sheet"])


def _raise(e: CostSheetError):
    raise HTTPException(status_code=e.status, detail=e.message)


async def _conflict(db: AsyncSession, detail: str):
    """A unique index caught a concurrent write (two syncs, two saves of the
    same machine rate): nothing of this request is kept."""
    await db.rollback()
    raise HTTPException(status_code=409, detail=detail)


class MachineRateBody(BaseModel):
    version_id: int
    # None removes the machine's own rate (the class rate applies again).
    hourly_rate: Optional[float] = Field(None, ge=0, lt=1e8, allow_inf_nan=False)
    currency: Optional[str] = Field(None, max_length=3)
    note: Optional[str] = Field(None, max_length=2000)
    # The rate typed in the plant's local currency (Silao: MXN); hourly_rate
    # is then computed at the version's exchange rate. null removes the rate.
    entered_rate: Optional[float] = Field(None, ge=0, lt=1e10, allow_inf_nan=False)
    entered_currency: Optional[str] = Field(None, max_length=3)


class PlantMapBody(BaseModel):
    mapping: dict[str, Optional[int]]


async def _status(db: AsyncSession, user: User) -> dict:
    org = user.organization_id
    return {
        "machinedb": machinedb_client.config_status(),
        "last_sync": await msvc.last_sync(db, org),
        "can_sync": await msvc.can_sync(db, user),
        "can_edit_rates": await svc.can_edit(db, user),
        "plant_map": await msvc.plant_map(db, org),
        "currencies": list(CURRENCIES),
    }


@router.get("")
async def list_machines(version_id: Optional[int] = None, plant_id: Optional[int] = None,
                        active_only: bool = False, min_tonnage: Optional[float] = None,
                        max_tonnage: Optional[float] = None,
                        current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """The synced machines; with version_id each carries its own rate and the
    class rate of its plant in that version (default: the version valid
    today)."""
    org = current_user.organization_id
    try:
        v = (await svc.get_version(db, org, version_id) if version_id
             else await svc.version_on(db, org))
    except CostSheetError as e:
        _raise(e)
    machines = await msvc.list_machines(
        db, org, version=v, plant_id=plant_id, active_only=active_only,
        min_tonnage=min_tonnage, max_tonnage=max_tonnage)
    return {"version_id": v.id if v else None, "machines": machines,
            **await _status(db, current_user)}


@router.post("/sync")
async def sync(force: bool = False, current_user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    """Sync the caller's organisation only. force applies an answer the
    guard refused (empty list, mostly unreadable rows, most machines gone)."""
    if not await msvc.can_sync(db, current_user):
        raise HTTPException(403, "Only Sales, Finance or an admin may sync the machines")
    try:
        try:
            result = await msvc.sync_machines(db, current_user.organization_id,
                                              current_user.id, force=force)
        except CostSheetError as e:
            await db.commit()             # keep the failed attempt on record
            _raise(e)
        await db.commit()
    except IntegrityError:
        await _conflict(db, "Another sync of the machines ran at the same time. "
                            "Reload to see its result.")
    return result


@router.put("/plant-map")
async def put_plant_map(body: PlantMapBody, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Merge into the hand mapping: a plant id maps, null keeps the
    MachineDB plant unmapped on purpose; keys not named stay as they are."""
    if not await msvc.can_sync(db, current_user):
        raise HTTPException(403, "Only Sales, Finance or an admin may map MachineDB plants")
    try:
        mapping = await msvc.set_plant_map(db, current_user.organization_id, body.mapping,
                                           current_user.id)
    except CostSheetError as e:
        _raise(e)
    await db.commit()
    return mapping


@router.delete("/plant-map/{key}")
async def delete_plant_map(key: str, current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """Drop one hand mapping; the default by plant name applies again."""
    if not await msvc.can_sync(db, current_user):
        raise HTTPException(403, "Only Sales, Finance or an admin may map MachineDB plants")
    try:
        mapping = await msvc.unmap_plant(db, current_user.organization_id, key,
                                         current_user.id)
    except CostSheetError as e:
        _raise(e)
    await db.commit()
    return mapping


@router.put("/{machine_id}/rate")
async def put_rate(machine_id: int, body: MachineRateBody,
                   current_user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    org = current_user.organization_id
    try:
        await svc.require_edit(db, current_user)
        v = await svc.get_version(db, org, body.version_id)
        sent = body.model_fields_set
        await msvc.set_machine_rate(
            db, v, machine_id, hourly_rate=body.hourly_rate, currency=body.currency,
            note=body.note if "note" in sent else ...,
            entered_rate=body.entered_rate if "entered_rate" in sent else ...,
            entered_currency=body.entered_currency)
        await db.commit()
    except CostSheetError as e:
        _raise(e)
    except IntegrityError:
        await _conflict(db, "This machine's rate was saved at the same time by someone "
                            "else. Reload and edit that rate instead.")
    rows = await msvc.list_machines(db, org, version=v)
    return next((m for m in rows if m["id"] == machine_id), None)
