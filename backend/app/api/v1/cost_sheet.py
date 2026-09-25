"""Cost sheet API (spec §15 / §15a): Finance's versioned rates.

Read: everyone in the org (rates are public by design). Write: Finance
members or admins, acts-as aware (cost_sheet_service.can_edit). Thin routes
over cost_sheet_service; every write commits here.
"""
from datetime import date
from typing import Literal, Optional

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.cost_sheet import CostSheetMachineClass, SETTING_REVIEW_MONTHS, CURRENCIES
from app.models.workflow import Department
from app.services import cost_sheet_service as svc
from app.services.cost_sheet_service import CostSheetError

class _FiniteJsonRoute(APIRoute):
    """Refuse NaN / Infinity in a JSON body with a plain 422 before FastAPI
    parses it. Python's json accepts those tokens, and FastAPI's own 422
    would then echo the NaN back and fail to serialise it (a 500)."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            if request.method in ("POST", "PUT", "PATCH"):
                raw = await request.body()
                if raw:
                    def _reject(token):
                        raise ValueError(token)
                    try:
                        json.loads(raw, parse_constant=_reject)
                    except ValueError as e:
                        if str(e) in ("NaN", "Infinity", "-Infinity"):
                            return JSONResponse(status_code=422, content={
                                "detail": "Numbers must be finite (no NaN or Infinity)"})
            return await handler(request)
        return guarded


router = APIRouter(prefix="/cost-sheet", tags=["cost-sheet"], route_class=_FiniteJsonRoute)

Section = Literal["rates", "machines", "sampling", "overheads"]


def _raise(e: CostSheetError):
    raise HTTPException(status_code=e.status, detail=e.message)


# ---------------------------------------------------------------- schemas

class DraftCreate(BaseModel):
    based_on_version_id: Optional[int] = None


class DraftUpdate(BaseModel):
    valid_from: Optional[date] = None
    note: Optional[str] = Field(None, max_length=2000)


class PublishBody(BaseModel):
    valid_from: date
    note: Optional[str] = Field(None, max_length=2000)
    # A valid_from in the past re-prices what was booked since; the caller
    # has to say it means it.
    confirm_backdated: bool = False


def _num(hi: float, lo: float = 0):
    """A finite number in [lo, hi). NaN/Infinity are refused here with a 422,
    before they can reach a Numeric column (and lock the draft with 500s)."""
    return Field(None, ge=lo, lt=hi, allow_inf_nan=False)


class RowBody(BaseModel):
    """Union of the four row shapes; the service keeps the fields its section
    knows and validates them again (bounds, finiteness, per-kind limits)."""
    department_id: Optional[int] = None
    position: Optional[str] = Field(None, max_length=80)
    plant_id: Optional[int] = None
    hourly_rate: Optional[float] = _num(1e8)
    currency: Optional[str] = Field(None, max_length=3)
    min_factor: Optional[float] = _num(100)
    note: Optional[str] = Field(None, max_length=2000)
    machine_class_id: Optional[int] = None
    machine_class: Optional[str] = Field(None, max_length=40)
    machine_ref: Optional[str] = Field(None, max_length=80)
    tonnage_min: Optional[int] = Field(None, ge=0, lt=1_000_000)
    tonnage_max: Optional[int] = Field(None, ge=0, lt=1_000_000)
    mode: Optional[Literal["flat", "components"]] = None
    flat_price: Optional[float] = _num(1e10)
    setup_hours: Optional[float] = _num(1e6)
    run_hours_default: Optional[float] = _num(1e6)
    labour_hours: Optional[float] = _num(1e6)
    labour_department_id: Optional[int] = None
    labour_position: Optional[str] = Field(None, max_length=80)
    handling_cost: Optional[float] = _num(1e10)
    kind: Optional[Literal["percent", "per_hour"]] = None
    # percent: 0 to 300; per_hour: 0 to 1e6 (the service checks per kind)
    value: Optional[float] = _num(1e6)


class MachineClassBody(BaseModel):
    name: Optional[str] = Field(None, max_length=40)
    tonnage_min: Optional[int] = Field(None, ge=0, lt=1_000_000)
    tonnage_max: Optional[int] = Field(None, ge=0, lt=1_000_000)
    sort_order: Optional[int] = Field(None, ge=0, lt=10_000)
    is_active: Optional[bool] = None


class SettingsBody(BaseModel):
    review_months: int = Field(..., ge=1, le=120)


class PlantCurrencyBody(BaseModel):
    currency: str = Field(..., min_length=3, max_length=3)


def _class_dict(c: CostSheetMachineClass) -> dict:
    return {"id": c.id, "name": c.name, "tonnage_min": c.tonnage_min,
            "tonnage_max": c.tonnage_max, "sort_order": c.sort_order,
            "is_active": c.is_active}


# ---------------------------------------------------------------- overview

@router.get("")
async def overview(current_user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    """Everything the page needs to open: versions with validity, which is
    current and which is the draft, rights, stale state, and the lookups."""
    org = current_user.organization_id
    versions = await svc.list_versions(db, org)
    valid = svc.validity(versions)
    current = await svc.version_on(db, org)
    draft = next((v for v in versions if v.status == "draft"), None)
    deps = (await db.execute(select(Department.id, Department.name, Department.is_active)
                             .order_by(Department.sort_order, Department.name))).all()
    return {
        "versions": [svc.version_summary(v, valid) for v in reversed(versions)],
        "current_version_id": current.id if current else None,
        "draft_version_id": draft.id if draft else None,
        "can_edit": await svc.can_edit(db, current_user),
        "stale": await svc.stale_status(db, org),
        "departments": [{"id": d.id, "name": d.name, "is_active": d.is_active} for d in deps],
        # Inactive plants too: migrated rows may still name one.
        "plants": await svc.plant_currencies(db, org),
        "currencies": list(CURRENCIES),
        "machine_classes": [_class_dict(c) for c in await svc.list_machine_classes(db, org)],
    }


@router.get("/review-task")
async def review_task(current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """The My Tasks item "Review the cost sheet" (spec §15): due for members
    of Finance (acts-as aware) when stale_status says the latest published
    version is older than the review period, or nothing is published."""
    from app.services.workflow_service import WorkflowService
    fin = await svc.finance_department_id(db)
    is_finance = fin is not None and fin in await WorkflowService.effective_department_ids(
        db, current_user)
    if not is_finance:
        return {"due": False, "is_finance": False, "stale": None}
    stale = await svc.stale_status(db, current_user.organization_id)
    return {"due": bool(stale["stale"]), "is_finance": True, "stale": stale}


@router.get("/versions/{version_id}")
async def get_version(version_id: int, current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    try:
        v = await svc.get_version(db, current_user.organization_id, version_id)
    except CostSheetError as e:
        _raise(e)
    valid = svc.validity(await svc.list_versions(db, current_user.organization_id))
    return svc.version_detail(v, valid)


@router.get("/versions/{version_id}/diff")
async def diff(version_id: int, against: Optional[int] = None,
               current_user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    """Diff to `against`, default the previous version (a draft: the one it
    was copied from)."""
    org = current_user.organization_id
    try:
        v = await svc.get_version(db, org, version_id)
        old = (await svc.get_version(db, org, against) if against
               else await svc.previous_version(db, v))
    except CostSheetError as e:
        _raise(e)
    return svc.diff_versions(old, v)


@router.get("/versions/{version_id}/export")
async def export(version_id: int, format: Literal["csv", "xlsx"] = "xlsx",
                 section: Literal["Positions", "Machines", "Sampling", "Overheads"] = "Positions",
                 current_user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    try:
        v = await svc.get_version(db, current_user.organization_id, version_id)
    except CostSheetError as e:
        _raise(e)
    stem = f"cost-sheet-v{v.version}"
    if format == "csv":
        body = await svc.export_csv(db, v, section)
        return Response(content=body.encode("utf-8-sig"), media_type="text/csv",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{stem}-{section.lower()}.csv"'})
    return Response(
        content=await svc.export_xlsx(db, v),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{stem}.xlsx"'})


# ---------------------------------------------------------------- lookups

@router.get("/lookup/rate")
async def lookup_rate(department_id: int, position: Optional[str] = None,
                      plant_id: Optional[int] = None, on_date: Optional[date] = None,
                      current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """The effective labour rate (overhead applied) valid on on_date."""
    hit = await svc.effective_labour_rate(db, current_user.organization_id, department_id,
                                          position, plant_id, on_date)
    return hit.as_dict() if hit else None


@router.get("/lookup/machine")
async def lookup_machine(machine_class: str, plant_id: Optional[int] = None,
                         machine_ref: Optional[str] = None, on_date: Optional[date] = None,
                         current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    hit = await svc.machine_rate_for(db, current_user.organization_id, machine_class,
                                     plant_id, on_date, machine_ref)
    return hit.as_dict() if hit else None


@router.get("/lookup/sampling")
async def lookup_sampling(machine_class: str, plant_id: Optional[int] = None,
                          run_hours: Optional[float] = None, on_date: Optional[date] = None,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    hit = await svc.sampling_price_for(db, current_user.organization_id, machine_class,
                                       plant_id, on_date, run_hours)
    return hit.as_dict() if hit else None


# ---------------------------------------------------------------- writes

async def _editable(db, user, version_id: int):
    await svc.require_edit(db, user)
    return await svc.get_version(db, user.organization_id, version_id)


async def _detail(db, v):
    await db.commit()
    await db.refresh(v)
    valid = svc.validity(await svc.list_versions(db, v.organization_id))
    return svc.version_detail(v, valid)


@router.post("/drafts", status_code=201)
async def create_draft(body: DraftCreate, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    try:
        await svc.require_edit(db, current_user)
        v = await svc.create_draft(db, current_user.organization_id, current_user.id,
                                   body.based_on_version_id)
    except CostSheetError as e:
        _raise(e)
    return await _detail(db, v)


@router.patch("/versions/{version_id}")
async def update_draft(version_id: int, body: DraftUpdate,
                       current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    try:
        v = await _editable(db, current_user, version_id)
        await svc.update_draft(db, v, valid_from=body.valid_from, note=body.note,
                               fields=body.model_fields_set)
    except CostSheetError as e:
        _raise(e)
    return await _detail(db, v)


@router.delete("/versions/{version_id}", status_code=204)
async def delete_draft(version_id: int, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    try:
        v = await _editable(db, current_user, version_id)
        await svc.delete_draft(db, v)
    except CostSheetError as e:
        _raise(e)
    await db.commit()
    return Response(status_code=204)


@router.post("/versions/{version_id}/publish")
async def publish(version_id: int, body: PublishBody,
                  current_user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    try:
        v = await _editable(db, current_user, version_id)
        await svc.publish(db, v, current_user.id, body.valid_from, body.note,
                          confirm_backdated=body.confirm_backdated)
    except CostSheetError as e:
        _raise(e)
    return await _detail(db, v)


@router.post("/versions/{version_id}/{section}", status_code=201)
async def add_row(version_id: int, section: Section, body: RowBody,
                  current_user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    try:
        v = await _editable(db, current_user, version_id)
        await svc.add_row(db, v, section, body.model_dump(exclude_unset=True))
    except CostSheetError as e:
        _raise(e)
    return await _detail(db, v)


@router.patch("/versions/{version_id}/{section}/{row_id}")
async def update_row(version_id: int, section: Section, row_id: int, body: RowBody,
                     current_user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    try:
        v = await _editable(db, current_user, version_id)
        await svc.update_row(db, v, section, row_id, body.model_dump(exclude_unset=True))
    except CostSheetError as e:
        _raise(e)
    return await _detail(db, v)


@router.delete("/versions/{version_id}/{section}/{row_id}")
async def delete_row(version_id: int, section: Section, row_id: int,
                     current_user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    try:
        v = await _editable(db, current_user, version_id)
        await svc.delete_row(db, v, section, row_id)
    except CostSheetError as e:
        _raise(e)
    return await _detail(db, v)


# ---------------------------------------------------------------- machine classes

@router.get("/machine-classes")
async def machine_classes(include_inactive: bool = False,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    return [_class_dict(c) for c in await svc.list_machine_classes(
        db, current_user.organization_id, include_inactive)]


@router.post("/machine-classes", status_code=201)
async def add_machine_class(body: MachineClassBody,
                            current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    try:
        await svc.require_edit(db, current_user)
        c = await svc.add_machine_class(db, current_user.organization_id,
                                        body.model_dump(exclude_unset=True))
        await db.commit()
    except CostSheetError as e:
        _raise(e)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A machine class with this name exists already")
    return _class_dict(c)


@router.patch("/machine-classes/{class_id}")
async def update_machine_class(class_id: int, body: MachineClassBody,
                               current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    """Rename or re-band a class; a rename follows into every row using it."""
    try:
        await svc.require_edit(db, current_user)
        c = await svc.update_machine_class(db, current_user.organization_id, class_id,
                                           body.model_dump(exclude_unset=True))
        await db.commit()
    except CostSheetError as e:
        _raise(e)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A machine class with this name exists already")
    return _class_dict(c)


@router.delete("/machine-classes/{class_id}", status_code=204)
async def delete_machine_class(class_id: int, current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    """Soft: the class leaves the dropdowns; version rows keep its name."""
    try:
        await svc.require_edit(db, current_user)
    except CostSheetError as e:
        _raise(e)
    c = await db.get(CostSheetMachineClass, class_id)
    if c is None or c.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Machine class not found")
    c.is_active = False
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- settings

@router.get("/settings")
async def get_settings(current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    return {"review_months": await svc.review_months(db, current_user.organization_id)}


@router.put("/settings")
async def put_settings(body: SettingsBody, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    try:
        await svc.require_edit(db, current_user)
    except CostSheetError as e:
        _raise(e)
    await svc.set_setting(db, current_user.organization_id, SETTING_REVIEW_MONTHS,
                          str(body.review_months), current_user.id)
    await db.commit()
    return {"review_months": body.review_months}


# ---------------------------------------------------------------- plant currencies

@router.put("/plants/{plant_id}/currency")
async def put_plant_currency(plant_id: int, body: PlantCurrencyBody,
                             current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """Finance sets or confirms the currency a plant's rows are priced in."""
    try:
        await svc.require_edit(db, current_user)
        await svc.set_plant_currency(db, current_user.organization_id, plant_id,
                                     body.currency, current_user.id)
    except CostSheetError as e:
        _raise(e)
    await db.commit()
    return await svc.plant_currencies(db, current_user.organization_id)
