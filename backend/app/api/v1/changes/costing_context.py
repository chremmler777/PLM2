"""Costing priced from the cost sheet (spec §15 phase 2): the context the
costing table needs (plant, currency, cost sheet version, stale review,
machine classes) and the change's machine class."""
from datetime import date
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


# --- per-department costing pipeline (2026-10-14) ---------------------------
# A department finalizes its own costing as soon as its window is open (in
# costing, or in assessment once it submitted a feasible answer that owes a
# cost input), and reopens it while costing is open. See early_costing.

class CostingReopenIn(BaseModel):
    reason: Optional[str] = None


async def _costing_state(db, change_id: int, user) -> dict:
    from app.services import early_costing
    change = await _change(db, change_id, user)
    st = early_costing.state(change)
    return {"owed_department_ids": st["owed"],
            "finalized_department_ids": st["finalized"],
            "pending_department_ids":
                await ChangeService.costing_pending_department_ids(db, change)}


@router.post("/{change_id}/costing/departments/{department_id}/finalize")
async def finalize_department_costing(change_id: int, department_id: int,
                                      current_user: User = Depends(get_current_user),
                                      db: AsyncSession = Depends(get_db)):
    from app.services import early_costing
    change = await _change(db, change_id, current_user)
    try:
        await early_costing.finalize(db, change, department_id, current_user)
    except early_costing.EarlyCostingForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except early_costing.EarlyCostingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
    return await _costing_state(db, change_id, current_user)


@router.get("/{change_id}/costing/departments/{department_id}/finalize-check")
async def finalize_check(change_id: int, department_id: int,
                         current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Christoph 2026-11-08: why Finalize is refused now (all reasons) and
    the lines missing something, for the department's red marks."""
    from app.services import early_costing
    change = await _change(db, change_id, current_user)
    return await early_costing.finalize_reasons(db, change, department_id)


@router.post("/{change_id}/costing/departments/{department_id}/reopen")
async def reopen_department_costing(change_id: int, department_id: int,
                                    body: Optional[CostingReopenIn] = None,
                                    current_user: User = Depends(get_current_user),
                                    db: AsyncSession = Depends(get_db)):
    from app.services import early_costing
    change = await _change(db, change_id, current_user)
    try:
        await early_costing.reopen(db, change, department_id, current_user,
                                   body.reason if body else None)
    except early_costing.EarlyCostingForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except early_costing.EarlyCostingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _costing_state(db, change_id, current_user)


# --- spec §4: "<Dept> has no cost" (C18) and waiting on a supplier ----------

class NoCostIn(BaseModel):
    reason: str                       # no_work | absorbed | supplier
    hours: Optional[float] = None     # absorbed: the hours absorbed (> 0)


@router.post("/{change_id}/costing/departments/{department_id}/no-cost")
async def department_no_cost(change_id: int, department_id: int, body: NoCostIn,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """C18: the department has no cost (no work / absorbed + hours / the
    supplier does it); finalizes its costing. Its members, PM, admin."""
    from app.services import early_costing
    change = await _change(db, change_id, current_user)
    try:
        await early_costing.no_cost(db, change, department_id, current_user,
                                    body.reason, body.hours)
    except early_costing.EarlyCostingForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except early_costing.EarlyCostingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    # Christoph 2026-11-09: assessment & costing runs on its own
    from app.services import auto_advance
    await auto_advance.run_after(db, change_id, current_user)
    return await _costing_state(db, change_id, current_user)


class SupplierWaitIn(BaseModel):
    department_id: int
    vendor_name: str
    asked_on: date
    expected_by: date
    position_id: Optional[int] = None
    note: Optional[str] = None


class SupplierWaitCloseIn(BaseModel):
    reason: str                       # received | price_on_estimate | not_needed
    note: Optional[str] = None


async def _waits(db, change) -> list[dict]:
    from sqlalchemy import select
    from app.models.change_cost import SupplierWait
    from app.services import supplier_wait_service as waits
    rows = list((await db.execute(
        select(SupplierWait).where(SupplierWait.change_id == change.id)
        .order_by(SupplierWait.closed_at.is_not(None), SupplierWait.asked_on,
                  SupplierWait.id))).scalars().all())
    return await waits.serialize(db, rows)


@router.get("/{change_id}/supplier-waits")
async def list_supplier_waits(change_id: int,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    change = await _change(db, change_id, current_user)
    return await _waits(db, change)


@router.post("/{change_id}/supplier-waits")
async def start_supplier_wait(change_id: int, body: SupplierWaitIn,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """Spec §4: the department waits on a supplier (vendor, asked on,
    expected by). Its members, PM, admin; costing or implementation."""
    from app.services import supplier_wait_service as waits
    change = await _change(db, change_id, current_user)
    try:
        await waits.create(db, change, current_user, department_id=body.department_id,
                           vendor_name=body.vendor_name, asked_on=body.asked_on,
                           expected_by=body.expected_by, position_id=body.position_id,
                           note=body.note)
    except waits.SupplierWaitForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except waits.SupplierWaitError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _waits(db, change)


@router.post("/{change_id}/supplier-waits/{wait_id}/reopen")
async def reopen_supplier_wait(change_id: int, wait_id: int,
                               current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    """Christoph 2026-11-08: undo 'Quote received' / 'not needed' clicked by
    accident: the wait is open again (only while no quote of that shop is
    filed on its line)."""
    from app.models.change_cost import SupplierWait, CostingPosition
    from app.services import supplier_wait_service as waits
    from app.services.change_service import ChangeService
    change = await _change(db, change_id, current_user)
    w = await db.get(SupplierWait, wait_id)
    if w is None or w.change_id != change.id:
        raise HTTPException(status_code=404, detail="Supplier wait not found")
    if not await waits._may_act(db, change, w.department_id, current_user):
        raise HTTPException(status_code=403, detail="Only that department, PM or an admin")
    if w.position_id is not None:
        pos = await db.get(CostingPosition, w.position_id)
        if pos and any(o.vendor_name.strip().lower() == w.vendor_name.strip().lower() for o in pos.offers):
            raise HTTPException(status_code=400,
                                detail="A quote of this shop is filed: delete that quote first")
    old = w.close_reason
    w.closed_at = None
    w.closed_by = None
    w.close_reason = None
    await ChangeService.append_changelog(
        db, change, "supplier_wait_reopened",
        f"Waiting on {w.vendor_name} again (was: {old})", current_user.id,
        for_department_id=w.department_id)
    await db.commit()
    return await _waits(db, change)


@router.post("/{change_id}/supplier-waits/{wait_id}/close")
async def close_supplier_wait(change_id: int, wait_id: int, body: SupplierWaitCloseIn,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """Received / not needed (the department), or §5 "Price on estimate"
    (the lead, PM, admin)."""
    from app.services import supplier_wait_service as waits
    change = await _change(db, change_id, current_user)
    try:
        await waits.close(db, change, wait_id, current_user, body.reason, body.note)
    except waits.SupplierWaitForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except waits.SupplierWaitError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _waits(db, change)
