"""Cost sheet service (spec §15 / §15a / §15b).

Everything that reads a price for an hour goes through here: position rates,
the effective labour rate with overhead, machine rates by class, sampling
prices. Everything that changes the sheet goes through here too: drafts,
row edits, publish. The router is a thin shell over these functions and
phase 2 (costing, P&L, bookings) calls the lookups directly.

Validity chain: published versions of an org ordered by valid_from; each is
valid from its valid_from until the day before the next one's valid_from
(the latest is open-ended). Publishing requires a valid_from strictly after
the latest published one, so the chain is always linear.
"""
from __future__ import annotations

import calendar
import csv
import io
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cost_sheet import (
    CostSheetVersion, CostSheetRate, CostSheetMachineRate, CostSheetMachineClass,
    CostSheetSamplingRate, CostSheetOverhead, OrgSetting,
    OVERHEAD_KINDS, SAMPLING_MODES, FINANCE_DEPARTMENT, EDITOR_DEPARTMENTS, DEFAULT_REVIEW_MONTHS,
    SETTING_REVIEW_MONTHS, SETTING_PLANT_CURRENCY_CONFIRMED, CURRENCIES,
)
from app.models.cost_sheet_machines import CostSheetMachineItemRate
from app.core.display import fmt_date
from app.models.entities import Plant
from app.models.workflow import Department
from app.utils.clock import business_today


class CostSheetError(Exception):
    """A request the sheet refuses. status is the HTTP code the router uses."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- helpers

def add_months(d: date, months: int) -> date:
    """d plus N calendar months, clamped to the month's last day."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _norm_position(position: Optional[str]) -> Optional[str]:
    if position is None:
        return None
    position = position.strip()
    return position or None


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


# ---------------------------------------------------------------- rights

async def finance_department_id(db: AsyncSession) -> Optional[int]:
    return (await db.execute(select(Department.id).where(
        Department.name == FINANCE_DEPARTMENT))).scalar_one_or_none()


async def editor_department_ids(db: AsyncSession) -> set[int]:
    """Sales and Finance: the departments whose members keep the rates."""
    return set((await db.execute(select(Department.id).where(
        Department.name.in_(EDITOR_DEPARTMENTS)))).scalars().all())


async def can_edit(db: AsyncSession, user) -> bool:
    """Sales or Finance members, or admins: they start drafts, edit rows and
    publish. Acts-as aware: an admin acting as a department is that
    department only (spec D2), so acting as Sales or Finance may edit and
    acting as anything else may not."""
    from app.services.workflow_service import WorkflowService
    if getattr(user, "acts_as_department_id", None) is None and user.role == "admin":
        return True
    editors = await editor_department_ids(db)
    if not editors:
        return False
    return bool(editors & set(await WorkflowService.effective_department_ids(db, user)))


async def require_edit(db: AsyncSession, user) -> None:
    if not await can_edit(db, user):
        raise CostSheetError("Only Sales, Finance or an admin may edit the cost sheet", 403)


# ---------------------------------------------------------------- settings

async def get_setting(db: AsyncSession, org_id: int, key: str) -> Optional[str]:
    return (await db.execute(select(OrgSetting.value).where(
        OrgSetting.organization_id == org_id, OrgSetting.key == key))).scalar_one_or_none()


async def set_setting(db: AsyncSession, org_id: int, key: str, value: Optional[str],
                      user_id: Optional[int] = None) -> None:
    row = (await db.execute(select(OrgSetting).where(
        OrgSetting.organization_id == org_id, OrgSetting.key == key))).scalar_one_or_none()
    if row is None:
        row = OrgSetting(organization_id=org_id, key=key)
        db.add(row)
    row.value = value
    row.updated_by = user_id
    row.updated_at = datetime.utcnow()
    await db.flush()


async def review_months(db: AsyncSession, org_id: int) -> int:
    raw = await get_setting(db, org_id, SETTING_REVIEW_MONTHS)
    try:
        n = int(raw) if raw is not None else DEFAULT_REVIEW_MONTHS
    except ValueError:
        n = DEFAULT_REVIEW_MONTHS
    return n if n > 0 else DEFAULT_REVIEW_MONTHS


# ---------------------------------------------------------------- versions

async def list_versions(db: AsyncSession, org_id: int) -> list[CostSheetVersion]:
    return list((await db.execute(select(CostSheetVersion).where(
        CostSheetVersion.organization_id == org_id).order_by(
        CostSheetVersion.version))).scalars().all())


def _published_chain(versions: Iterable[CostSheetVersion]) -> list[CostSheetVersion]:
    return sorted((v for v in versions if v.status == "published" and v.valid_from),
                  key=lambda v: (v.valid_from, v.version))


def validity(versions: Iterable[CostSheetVersion]) -> dict[int, tuple[date, Optional[date]]]:
    """version id -> (valid_from, valid_to inclusive or None) for published versions."""
    chain = _published_chain(versions)
    out: dict[int, tuple[date, Optional[date]]] = {}
    for i, v in enumerate(chain):
        nxt = chain[i + 1].valid_from if i + 1 < len(chain) else None
        out[v.id] = (v.valid_from, nxt - timedelta(days=1) if nxt else None)
    return out


async def version_on(db: AsyncSession, org_id: int,
                     on_date: Optional[date] = None) -> Optional[CostSheetVersion]:
    """The published version valid on on_date (default today). None before
    the first version's valid_from or when nothing is published."""
    on_date = on_date or business_today()
    return (await db.execute(select(CostSheetVersion).where(
        CostSheetVersion.organization_id == org_id,
        CostSheetVersion.status == "published",
        CostSheetVersion.valid_from <= on_date,
    ).order_by(CostSheetVersion.valid_from.desc(),
               CostSheetVersion.version.desc()).limit(1))).scalar_one_or_none()


async def earliest_published(db: AsyncSession, org_id: int) -> Optional[CostSheetVersion]:
    return (await db.execute(select(CostSheetVersion).where(
        CostSheetVersion.organization_id == org_id,
        CostSheetVersion.status == "published",
        CostSheetVersion.valid_from.is_not(None),
    ).order_by(CostSheetVersion.valid_from.asc(),
               CostSheetVersion.version.asc()).limit(1))).scalar_one_or_none()


async def pricing_version(db: AsyncSession, org_id: int,
                          on_date: Optional[date] = None) -> Optional[CostSheetVersion]:
    """The version that prices a change created on on_date: the one valid
    that day, or the first published version for a date before it (the
    change is priced, not left without rates; the label says so)."""
    return (await version_on(db, org_id, on_date)) or await earliest_published(db, org_id)


async def latest_published(db: AsyncSession, org_id: int) -> Optional[CostSheetVersion]:
    return (await db.execute(select(CostSheetVersion).where(
        CostSheetVersion.organization_id == org_id,
        CostSheetVersion.status == "published",
    ).order_by(CostSheetVersion.valid_from.desc(),
               CostSheetVersion.version.desc()).limit(1))).scalar_one_or_none()


async def open_draft(db: AsyncSession, org_id: int) -> Optional[CostSheetVersion]:
    return (await db.execute(select(CostSheetVersion).where(
        CostSheetVersion.organization_id == org_id,
        CostSheetVersion.status == "draft").limit(1))).scalar_one_or_none()


async def get_version(db: AsyncSession, org_id: int, version_id: int) -> CostSheetVersion:
    v = await db.get(CostSheetVersion, version_id)
    if v is None or v.organization_id != org_id:
        raise CostSheetError("Cost sheet version not found", 404)
    return v


def _require_draft(v: CostSheetVersion) -> None:
    if v.status != "draft":
        raise CostSheetError("A published version is frozen; start a new draft", 409)


_ROW_COPY = {
    "rates": (CostSheetRate, ("department_id", "position", "plant_id", "hourly_rate",
                              "currency", "min_factor", "note",
                              "entered_rate", "entered_currency")),
    "machines": (CostSheetMachineRate, ("plant_id", "machine_class_id", "machine_class",
                                        "machine_ref",
                                        "tonnage_min", "tonnage_max", "hourly_rate",
                                        "currency", "note",
                                        "entered_rate", "entered_currency")),
    "sampling": (CostSheetSamplingRate, ("plant_id", "machine_class_id", "machine_class",
                                         "mode", "flat_price",
                                         "setup_hours", "run_hours_default", "labour_hours",
                                         "labour_department_id", "labour_position",
                                         "handling_cost", "currency", "note")),
    "overheads": (CostSheetOverhead, ("plant_id", "department_id", "kind", "value", "currency",
                                      "note")),
    # Per-machine rates of MachineDB presses (105); edited through
    # cost_sheet_machines_service, copied and diffed here like the rest.
    "machine_items": (CostSheetMachineItemRate, ("machine_id", "hourly_rate", "currency",
                                                 "note", "entered_rate", "entered_currency")),
}
_REL = {"rates": "rates", "machines": "machine_rates", "sampling": "sampling_rates",
        "overheads": "overheads", "machine_items": "machine_item_rates"}
SECTIONS = tuple(_ROW_COPY)


async def create_draft(db: AsyncSession, org_id: int, user_id: Optional[int],
                       based_on_version_id: Optional[int] = None) -> CostSheetVersion:
    """A new draft, copied from based_on (default: the latest published
    version). One open draft per org: a second one would fork the sheet."""
    if await open_draft(db, org_id) is not None:
        raise CostSheetError("There is already an open draft", 409)
    base = (await get_version(db, org_id, based_on_version_id)
            if based_on_version_id else await latest_published(db, org_id))
    nxt = (await db.execute(select(func.coalesce(func.max(CostSheetVersion.version), 0))
                            .where(CostSheetVersion.organization_id == org_id))).scalar() + 1
    draft = CostSheetVersion(organization_id=org_id, version=nxt, status="draft", draft_lock=1,
                             based_on_version_id=base.id if base else None,
                             # the exchange rates travel with the rates they priced
                             fx_rates=dict(base.fx_rates) if base and base.fx_rates else None,
                             created_by=user_id, created_at=datetime.utcnow())
    db.add(draft)
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent request opened a draft (or took the version number)
        # between our check and this insert; the index is the real guard.
        await db.rollback()
        raise CostSheetError("There is already an open draft", 409)
    if base is not None:
        for section, (model, cols) in _ROW_COPY.items():
            seen: set[tuple] = set()
            for row in getattr(base, _REL[section]):
                data = {c: getattr(row, c) for c in cols}
                if section == "rates":
                    data["position"] = None      # one row per department per plant
                    key = _duplicate_key(section, data)
                    if key in seen:
                        continue
                    seen.add(key)
                db.add(model(version_id=draft.id, **data))
        await db.flush()
    await db.refresh(draft)
    await seed_missing_departments(db, draft)
    return draft


async def routable_department_ids(db: AsyncSession) -> list[int]:
    """The departments an ECR can be routed to as R/A/S/C
    (models.change.ASSESSMENT_LETTERS), in their sort order: every active
    department. The routing standards name most of them and a routing
    deviation can add any active department with any of those letters, so
    each of them may book hours that need a rate. Retired departments
    (is_active false) cannot be routed any more."""
    return list((await db.execute(select(Department.id).where(
        Department.is_active.is_(True)).order_by(
        Department.sort_order, Department.id))).scalars().all())


async def seed_missing_departments(db: AsyncSession, v: CostSheetVersion) -> list[CostSheetRate]:
    """Give the draft one row with an EMPTY rate (None, never a guessed
    number) per routable department and active plant that has none yet. A
    department's all-plants row covers every plant. Costing then shows "No
    rate in the cost sheet" for those rows until Sales or Finance fills them.
    Published versions are frozen: refused."""
    _require_draft(v)
    await db.refresh(v, ["rates"])
    have = {(r.department_id, r.plant_id) for r in v.rates}
    plants = (await db.execute(select(Plant).where(
        Plant.organization_id == v.organization_id, Plant.is_active.is_(True))
        .order_by(Plant.id))).scalars().all()
    added = []
    for dep in await routable_department_ids(db):
        if (dep, None) in have:
            continue
        for p in plants:
            if (dep, p.id) not in have:
                row = CostSheetRate(version_id=v.id, department_id=dep, plant_id=p.id,
                                    position=None, hourly_rate=None,
                                    currency=p.currency or "EUR")
                db.add(row)
                added.append(row)
    if added:
        await db.flush()
        await db.refresh(v, ["rates"])
    return added


async def update_draft(db: AsyncSession, v: CostSheetVersion, *,
                       valid_from: Optional[date] = None, note: Optional[str] = None,
                       fields: Iterable[str] = ()) -> CostSheetVersion:
    _require_draft(v)
    if "valid_from" in fields:
        v.valid_from = valid_from
    if "note" in fields:
        v.note = note
    await db.flush()
    return v


async def delete_draft(db: AsyncSession, v: CostSheetVersion) -> None:
    _require_draft(v)
    await db.delete(v)
    await db.flush()


async def publish(db: AsyncSession, v: CostSheetVersion, user_id: Optional[int],
                  valid_from: date, note: Optional[str] = None, *,
                  confirm_backdated: bool = False,
                  today: Optional[date] = None) -> CostSheetVersion:
    """Freeze a draft. valid_from must lie after the latest published
    version's, which then ends the day before. A change is priced with the
    version valid on the day it was CREATED (costing_rates.change_pricing_date),
    so a valid_from in the past prices the changes created since then (their
    lines without a rate) and the hours booked since then from the new
    version: it needs confirm_backdated. Lines already priced keep their
    rate snapshot. Routable departments without a row get their empty rows
    (seed_missing_departments) before the version freezes.
    A draft identical to the version it was copied from is refused."""
    _require_draft(v)
    latest = await latest_published(db, v.organization_id)
    if latest is not None and valid_from <= latest.valid_from:
        raise CostSheetError(
            f"Valid from must be after {fmt_date(latest.valid_from)} "
            f"(version {latest.version})", 422)
    if not any(r.hourly_rate is not None for r in v.rates):
        raise CostSheetError("A version needs at least one department rate", 422)
    if valid_from < (today or business_today()) and not confirm_backdated:
        raise CostSheetError(
            "Valid from lies in the past. Changes created since then are priced with "
            "this version where a line has no rate yet, and hours booked since then "
            "use it too; lines already priced keep their rate. "
            "Confirm the backdated publish to go ahead", 422)
    for row in list(v.rates) + list(v.machine_rates) + list(v.machine_item_rates):
        if (row.entered_currency and row.entered_currency != row.currency
                and fx_rate(v, row.currency, row.entered_currency) is None):
            raise CostSheetError(
                f"A rate is typed in {row.entered_currency} but the version has no "
                f"{row.currency}/{row.entered_currency} exchange rate", 422)
    prev = await previous_version(db, v)
    if prev is not None and diff_is_empty(diff_versions(prev, v)):
        raise CostSheetError(f"Nothing changed since version {prev.version}", 409)
    # Departments activated since the draft started get their empty rows
    # now, so the published version names every routable department.
    await seed_missing_departments(db, v)
    v.valid_from = valid_from
    if note is not None:
        v.note = note
    v.draft_lock = None
    v.status = "published"
    v.published_at = datetime.utcnow()
    v.published_by = user_id
    await db.flush()
    return v


# ---------------------------------------------------------------- row edits

# Bounds per numeric column: (min inclusive, max exclusive). They sit well
# inside the Numeric precision of each column, so a value that passes can
# always be stored; NaN and infinities never pass (math.isfinite).
BOUNDS = {
    "hourly_rate": (0, 1e8), "flat_price": (0, 1e10), "handling_cost": (0, 1e10),
    "setup_hours": (0, 1e6), "run_hours_default": (0, 1e6), "labour_hours": (0, 1e6),
    "min_factor": (0, 100), "tonnage_min": (0, 1e6), "tonnage_max": (0, 1e6),
}
PERCENT_OVERHEAD_MAX = 300
PER_HOUR_OVERHEAD_MAX = 1e6


def _check_number(key: str, value, lo: float, hi: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise CostSheetError(f"{key} must be a number", 422)
    if not math.isfinite(f):
        raise CostSheetError(f"{key} must be a finite number", 422)
    if f < lo or f >= hi:
        raise CostSheetError(f"{key} must be between {lo:g} and {hi:g}", 422)
    return f


def normalize_currency(value) -> str:
    cur = str(value or "").strip().upper()
    if cur not in CURRENCIES:
        raise CostSheetError(
            f"Unknown currency {cur or '(empty)'}; use one of {', '.join(CURRENCIES)}", 422)
    return cur


async def plant_currency(db: AsyncSession, plant_id: Optional[int]) -> str:
    if plant_id is None:
        return "EUR"
    plant = await db.get(Plant, plant_id)
    return (plant.currency if plant is not None and plant.currency else "EUR")


async def resolve_machine_class(db: AsyncSession, org_id: int, class_id=None,
                                name=None) -> CostSheetMachineClass:
    """The org's class by id, or by name (case-blind). Rows must name a class
    that exists, so a rename can follow them."""
    if class_id is not None:
        c = await db.get(CostSheetMachineClass, class_id)
        if c is not None and c.organization_id == org_id:
            return c
    elif name:
        c = (await db.execute(select(CostSheetMachineClass).where(
            CostSheetMachineClass.organization_id == org_id,
            func.lower(CostSheetMachineClass.name) == name.strip().lower()))).scalars().first()
        if c is not None:
            return c
    raise CostSheetError("Unknown machine class; add it to the machine classes first", 422)


async def _validate_row(db: AsyncSession, org_id: int, section: str, data: dict,
                        class_changed: bool = True) -> None:
    for k, (lo, hi) in BOUNDS.items():
        if data.get(k) is not None:
            data[k] = _check_number(k, data[k], lo, hi)
    for k in ("tonnage_min", "tonnage_max"):
        if data.get(k) is not None:
            data[k] = int(data[k])
    if (data.get("tonnage_min") is not None and data.get("tonnage_max") is not None
            and data["tonnage_min"] > data["tonnage_max"]):
        raise CostSheetError("Tonnage from must not be above tonnage to", 422)
    if data.get("plant_id") is not None:
        plant = await db.get(Plant, data["plant_id"])
        if plant is None or plant.organization_id != org_id:
            raise CostSheetError("Unknown plant", 422)
    for key in ("department_id", "labour_department_id"):
        if data.get(key) is not None and await db.get(Department, data[key]) is None:
            raise CostSheetError("Unknown department", 422)
    if data.get("currency") is not None:
        data["currency"] = normalize_currency(data["currency"])
    for key in ("position", "labour_position", "machine_ref", "machine_class"):
        if key in data:
            data[key] = _norm_position(data[key])
    if section == "rates":
        if data.get("department_id") is None:
            raise CostSheetError("A rate needs a department", 422)
        # One row per department per plant: no positions any more (104). An
        # empty hourly_rate is allowed: "no rate yet", never a number.
        if "position" in data:
            data["position"] = None
    if section in ("machines", "sampling") and class_changed:
        if not data.get("machine_class") and data.get("machine_class_id") is None:
            raise CostSheetError("A machine class is required", 422)
        cls = await resolve_machine_class(
            db, org_id, class_id=data.get("machine_class_id"), name=data.get("machine_class"))
        data["machine_class_id"], data["machine_class"] = cls.id, cls.name
    if section == "machines" and data.get("hourly_rate") is None:
        raise CostSheetError("A machine rate needs an hourly rate", 422)
    if section == "sampling":
        if data.get("mode") not in SAMPLING_MODES:
            raise CostSheetError("Mode is flat or components", 422)
        if data["mode"] == "flat" and data.get("flat_price") is None:
            raise CostSheetError("A flat sampling price needs a price", 422)
        if (data["mode"] == "components" and (data.get("labour_hours") or 0) > 0
                and data.get("labour_department_id") is None):
            raise CostSheetError("Labour hours need a labour department", 422)
    if section == "overheads":
        if data.get("kind") not in OVERHEAD_KINDS:
            raise CostSheetError("Kind is percent or per_hour", 422)
        if data.get("value") is None:
            raise CostSheetError("An overhead needs a value", 422)
        hi = PERCENT_OVERHEAD_MAX + 1e-9 if data["kind"] == "percent" else PER_HOUR_OVERHEAD_MAX
        data["value"] = _check_number("value", data["value"], 0, hi)
        if data["kind"] == "percent":
            data["currency"] = None      # a percentage has no currency
        elif not data.get("currency"):
            data["currency"] = await plant_currency(db, data.get("plant_id"))


def _duplicate_key(section: str, data: dict) -> tuple:
    """What identifies a row within a version; text compares case-blind,
    the same way the lookups match."""
    key = _raw_key(section, data)
    return tuple(k.casefold() if isinstance(k, str) else k for k in key)


def _raw_key(section: str, data: dict) -> tuple:
    if section == "rates":
        return (data.get("department_id"), data.get("plant_id"))
    cls = data.get("machine_class_id") or data.get("machine_class")
    if section == "machines":
        return (data.get("plant_id"), cls, data.get("machine_ref"))
    if section == "sampling":
        return (data.get("plant_id"), cls)
    return (data.get("plant_id"), data.get("department_id"))


async def _rate_exists_message(db: AsyncSession, data: dict) -> str:
    dep = await db.get(Department, data.get("department_id"))
    plant = await db.get(Plant, data["plant_id"]) if data.get("plant_id") else None
    where = f"at {plant.name}" if plant is not None else "for all plants"
    return (f"{dep.name if dep else 'This department'} already has a rate {where} "
            f"in this version. Edit that row instead.")


async def _check_unique_row(db: AsyncSession, v: CostSheetVersion, section: str, data: dict,
                            exclude_id: Optional[int] = None) -> None:
    """_check_unique, with the department and plant named for a rate."""
    try:
        _check_unique(v, section, data, exclude_id)
    except CostSheetError as e:
        if section == "rates":
            raise CostSheetError(await _rate_exists_message(db, data), 409) from None
        raise e


def _check_unique(v: CostSheetVersion, section: str, data: dict,
                  exclude_id: Optional[int] = None) -> None:
    _, cols = _ROW_COPY[section]
    key = _duplicate_key(section, data)
    for row in getattr(v, _REL[section]):
        if row.id == exclude_id:
            continue
        if _duplicate_key(section, {c: getattr(row, c) for c in cols}) == key:
            raise CostSheetError("This combination already has a row in this version", 409)


async def add_row(db: AsyncSession, v: CostSheetVersion, section: str, data: dict):
    _require_draft(v)
    model, cols = _ROW_COPY[section]
    data = {k: data.get(k) for k in cols if k in data}
    if section == "sampling":
        data.setdefault("mode", "flat")
    if section == "overheads":
        data.setdefault("kind", "percent")
    if section != "overheads" and not data.get("currency"):
        data["currency"] = await plant_currency(db, data.get("plant_id"))
    await _apply_entered(db, v, section, data, set(data))
    await _validate_row(db, v.organization_id, section, data)
    await _check_unique_row(db, v, section, data)
    # None values are left out so column defaults (currency EUR) apply.
    row = model(version_id=v.id, **{k: val for k, val in data.items() if val is not None})
    db.add(row)
    await db.flush()
    await db.refresh(v)
    return row


def _find_row(v: CostSheetVersion, section: str, row_id: int):
    for row in getattr(v, _REL[section]):
        if row.id == row_id:
            return row
    raise CostSheetError("Row not found in this version", 404)


async def update_row(db: AsyncSession, v: CostSheetVersion, section: str, row_id: int,
                     changes: dict):
    _require_draft(v)
    row = _find_row(v, section, row_id)
    _, cols = _ROW_COPY[section]
    merged = {c: getattr(row, c) for c in cols}
    changes = {k: val for k, val in changes.items() if k in cols}
    # A new class name without an id picks the class by name.
    if "machine_class" in changes and "machine_class_id" not in changes:
        changes["machine_class_id"] = None
    merged.update(changes)
    if section != "overheads" and not merged.get("currency"):
        merged["currency"] = await plant_currency(db, merged.get("plant_id"))
    await _apply_entered(db, v, section, merged, set(changes))
    await _validate_row(db, v.organization_id, section, merged,
                        class_changed=("machine_class" in changes
                                       or changes.get("machine_class_id") is not None
                                       or merged.get("machine_class_id") is None))
    await _check_unique_row(db, v, section, merged, exclude_id=row.id)
    for c in cols:
        setattr(row, c, merged[c])
    await db.flush()
    return row


async def delete_row(db: AsyncSession, v: CostSheetVersion, section: str, row_id: int) -> None:
    _require_draft(v)
    row = _find_row(v, section, row_id)
    await db.delete(row)
    await db.flush()
    await db.refresh(v)


# ---------------------------------------------------------------- machine classes

async def list_machine_classes(db: AsyncSession, org_id: int,
                               include_inactive: bool = False) -> list[CostSheetMachineClass]:
    q = select(CostSheetMachineClass).where(CostSheetMachineClass.organization_id == org_id)
    if not include_inactive:
        q = q.where(CostSheetMachineClass.is_active.is_(True))
    return list((await db.execute(q.order_by(CostSheetMachineClass.sort_order,
                                             CostSheetMachineClass.id))).scalars().all())


async def add_machine_class(db: AsyncSession, org_id: int, data: dict) -> CostSheetMachineClass:
    name = _norm_position(data.get("name"))
    if not name:
        raise CostSheetError("A machine class needs a name", 422)
    await _check_class_name(db, org_id, name)
    c = CostSheetMachineClass(organization_id=org_id, name=name,
                              sort_order=int(data.get("sort_order") or 0),
                              is_active=True if data.get("is_active") is None else data["is_active"])
    _apply_class_band(c, data)
    db.add(c)
    await db.flush()
    return c


async def _check_class_name(db: AsyncSession, org_id: int, name: str,
                            exclude_id: Optional[int] = None) -> None:
    q = select(CostSheetMachineClass.id).where(
        CostSheetMachineClass.organization_id == org_id,
        func.lower(CostSheetMachineClass.name) == name.lower())
    if exclude_id is not None:
        q = q.where(CostSheetMachineClass.id != exclude_id)
    if (await db.execute(q)).first() is not None:
        raise CostSheetError("A machine class with this name exists already", 409)


def _apply_class_band(c: CostSheetMachineClass, data: dict) -> None:
    for k in ("tonnage_min", "tonnage_max"):
        if k in data:
            setattr(c, k, None if data[k] is None else int(_check_number(k, data[k], *BOUNDS[k])))
    if c.tonnage_min is not None and c.tonnage_max is not None and c.tonnage_min > c.tonnage_max:
        raise CostSheetError("Tonnage from must not be above tonnage to", 422)


async def update_machine_class(db: AsyncSession, org_id: int, class_id: int,
                               data: dict) -> CostSheetMachineClass:
    """Edit a class. A rename carries over to every row that references the
    class (drafts and published versions alike: the class is the same, only
    its label changes), so lookups and exports keep matching."""
    c = await db.get(CostSheetMachineClass, class_id)
    if c is None or c.organization_id != org_id:
        raise CostSheetError("Machine class not found", 404)
    if "name" in data:
        name = _norm_position(data["name"])
        if not name:
            raise CostSheetError("A machine class needs a name", 422)
        await _check_class_name(db, org_id, name, exclude_id=c.id)
        if name != c.name:
            for model in (CostSheetMachineRate, CostSheetSamplingRate):
                await db.execute(update(model).where(model.machine_class_id == c.id)
                                 .values(machine_class=name))
            c.name = name
    _apply_class_band(c, data)
    for k in ("sort_order", "is_active"):
        if data.get(k) is not None:
            setattr(c, k, data[k])
    await db.flush()
    return c


def class_for_tonnage(classes: Iterable[CostSheetMachineClass], tonnage: float) -> Optional[str]:
    """The class whose band contains tonnage (min exclusive, max inclusive,
    open bounds allowed). Used to default a change's machine class from the
    impacted tool's tonnage."""
    for c in classes:
        lo_ok = c.tonnage_min is None or tonnage > c.tonnage_min
        hi_ok = c.tonnage_max is None or tonnage <= c.tonnage_max
        if lo_ok and hi_ok and (c.tonnage_min is not None or c.tonnage_max is not None):
            return c.name
    return None


# ---------------------------------------------------------------- lookups

@dataclass
class RateHit:
    """One looked-up rate and where it came from. Costing lines store rate,
    version_id and version as the snapshot."""
    # None = incomplete: a part of the price is missing or in another
    # currency; breakdown["missing"] says which. Never guess a number.
    rate: Optional[float]
    currency: str
    version_id: int
    version: int
    row_id: int
    match: str                       # e.g. "department+position+plant"
    base_rate: Optional[float] = None
    overhead: Optional[dict] = None
    breakdown: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _pick_rate(rows: Iterable[CostSheetRate], department_id: int, position: Optional[str],
               plant_id: Optional[int]) -> tuple[Optional[CostSheetRate], str]:
    """The department's row at the plant, else its all-plants row. One row
    per department per plant (104): position is ignored (a costing line
    that names a labour position is priced from its department's row). A row
    whose rate is still empty is no rate: the all-plants row may stand in
    for it, else there is none (never 0)."""
    cands = [r for r in rows if r.department_id == department_id and r.hourly_rate is not None]
    order = ([(plant_id, "department+plant")] if plant_id is not None else []) \
        + [(None, "department")]
    for pl, label in order:
        for r in cands:
            if r.plant_id == pl:
                return r, label
    return None, ""


def _pick_overhead(rows: Iterable[CostSheetOverhead], department_id: Optional[int],
                   plant_id: Optional[int]) -> Optional[CostSheetOverhead]:
    """dept+plant > dept > plant > org."""
    rows = list(rows)
    for dep, pl in ((department_id, plant_id), (department_id, None),
                    (None, plant_id), (None, None)):
        for r in rows:
            if r.department_id == dep and r.plant_id == pl:
                return r
    return None


def apply_overhead(base: float, oh: Optional[CostSheetOverhead],
                   currency: Optional[str] = None) -> Optional[float]:
    """Base rate plus overhead. None when a per-hour overhead is in another
    currency than the rate: adding USD to EUR would be a wrong number."""
    if oh is None:
        return round(base, 2)
    if oh.kind == "percent":
        return round(base * (1 + float(oh.value) / 100.0), 2)
    if currency and oh.currency and oh.currency != currency:
        return None
    return round(base + float(oh.value), 2)


def _overhead_dict(oh: Optional[CostSheetOverhead]) -> Optional[dict]:
    if oh is None:
        return None
    return {"id": oh.id, "kind": oh.kind, "value": float(oh.value), "currency": oh.currency,
            "department_id": oh.department_id, "plant_id": oh.plant_id}


def rate_in_version(v: CostSheetVersion, department_id: int, position: Optional[str],
                    plant_id: Optional[int], *, with_overhead: bool = False) -> Optional[RateHit]:
    """The department's rate at the plant in v (position ignored, see
    _pick_rate); None when the sheet has no rate for it."""
    row, match = _pick_rate(v.rates, department_id, position, plant_id)
    if row is None:
        return None
    base = float(row.hourly_rate)
    hit = RateHit(rate=round(base, 2), currency=row.currency, version_id=v.id,
                  version=v.version, row_id=row.id, match=match, base_rate=round(base, 2))
    if with_overhead:
        oh = _pick_overhead(v.overheads, department_id, plant_id)
        hit.rate = apply_overhead(base, oh, row.currency)
        hit.overhead = _overhead_dict(oh)
        if hit.rate is None:
            hit.breakdown = {"missing": ["overhead_currency"]}
    return hit


async def rate_for(db: AsyncSession, org_id: int, department_id: int,
                   position: Optional[str] = None, plant_id: Optional[int] = None,
                   on_date: Optional[date] = None) -> Optional[RateHit]:
    """Base position rate (no overhead) in the version valid on on_date."""
    v = await version_on(db, org_id, on_date)
    return rate_in_version(v, department_id, position, plant_id) if v else None


async def effective_labour_rate(db: AsyncSession, org_id: int, department_id: int,
                                position: Optional[str] = None, plant_id: Optional[int] = None,
                                on_date: Optional[date] = None) -> Optional[RateHit]:
    """rate_for plus the most specific personnel overhead. hit.rate is the
    effective rate, hit.base_rate the position rate before overhead."""
    v = await version_on(db, org_id, on_date)
    return rate_in_version(v, department_id, position, plant_id, with_overhead=True) if v else None


def _class_match(row, machine_class) -> bool:
    """machine_class is a class id (int) or a name (case-blind)."""
    if isinstance(machine_class, int):
        return row.machine_class_id == machine_class
    return (row.machine_class or "").casefold() == str(machine_class).strip().casefold()


def _pick_machine(rows: Iterable[CostSheetMachineRate], machine_class,
                  plant_id: Optional[int], machine_ref: Optional[str]):
    """ref+plant > ref > class+plant > class (class rows have no ref)."""
    ref = _norm_position(machine_ref)
    rows = [r for r in rows if _class_match(r, machine_class)]
    order = []
    if ref:
        order += [(ref.casefold(), plant_id, "ref+plant"), (ref.casefold(), None, "ref")]
    order += [(None, plant_id, "class+plant"), (None, None, "class")]
    for rk, pl, label in order:
        if pl is None and label.endswith("plant"):
            continue
        for r in rows:
            rr = r.machine_ref.casefold() if r.machine_ref else None
            if rr == rk and r.plant_id == pl:
                return r, label
    return None, ""


def machine_rate_in_version(v: CostSheetVersion, machine_class: str, plant_id: Optional[int],
                            machine_ref: Optional[str] = None) -> Optional[RateHit]:
    row, match = _pick_machine(v.machine_rates, machine_class, plant_id, machine_ref)
    if row is None:
        return None
    r = round(float(row.hourly_rate), 2)
    return RateHit(rate=r, currency=row.currency, version_id=v.id, version=v.version,
                   row_id=row.id, match=match, base_rate=r)


async def machine_rate_for(db: AsyncSession, org_id: int, machine_class: str,
                           plant_id: Optional[int] = None, on_date: Optional[date] = None,
                           machine_ref: Optional[str] = None) -> Optional[RateHit]:
    v = await version_on(db, org_id, on_date)
    return machine_rate_in_version(v, machine_class, plant_id, machine_ref) if v else None


def sampling_in_version(v: CostSheetVersion, machine_class: str, plant_id: Optional[int],
                        run_hours: Optional[float] = None) -> Optional[RateHit]:
    """Price of ONE trial. Components: (setup + run hours) x machine rate +
    labour hours x effective labour rate + handling. hit.breakdown says which
    parts went in; a missing machine or labour rate is reported, not guessed."""
    rows = [r for r in v.sampling_rates if _class_match(r, machine_class)]
    row = next((r for r in rows if r.plant_id == plant_id and plant_id is not None), None)
    match = "class+plant"
    if row is None:
        row = next((r for r in rows if r.plant_id is None), None)
        match = "class"
    if row is None:
        return None
    if row.mode == "flat":
        price = round(float(row.flat_price or 0), 2)
        return RateHit(rate=price, currency=row.currency, version_id=v.id, version=v.version,
                       row_id=row.id, match=match, breakdown={"mode": "flat", "flat_price": price})
    setup = float(row.setup_hours or 0)
    run = float(run_hours if run_hours is not None else (row.run_hours_default or 0))
    key = row.machine_class_id if row.machine_class_id is not None else row.machine_class
    mhit = machine_rate_in_version(v, key, plant_id)
    labour_hours = float(row.labour_hours or 0)
    lhit = None
    if labour_hours and row.labour_department_id:
        lhit = rate_in_version(v, row.labour_department_id, row.labour_position, plant_id,
                               with_overhead=True)
    missing = []
    if (setup + run) and mhit is None:
        missing.append("machine_rate")
    elif (setup + run) and mhit.currency != row.currency:
        missing.append("machine_rate_currency")
    if labour_hours and (lhit is None or lhit.rate is None):
        missing.append("labour_rate")
    elif labour_hours and lhit.currency != row.currency:
        missing.append("labour_rate_currency")
    machine_cost = round((setup + run) * mhit.rate, 2) if mhit and (setup + run) else 0.0
    labour_cost = (round(labour_hours * lhit.rate, 2)
                   if lhit and lhit.rate is not None and labour_hours else 0.0)
    handling = float(row.handling_cost or 0)
    # An incomplete price is no price: a sum without its labour part would be
    # taken for the real cost of a trial.
    price = None if missing else round(machine_cost + labour_cost + handling, 2)
    return RateHit(rate=price, currency=row.currency, version_id=v.id, version=v.version,
                   row_id=row.id, match=match, breakdown={
                       "mode": "components", "setup_hours": setup, "run_hours": run,
                       "machine_rate": mhit.rate if mhit else None, "machine_cost": machine_cost,
                       "labour_hours": labour_hours, "labour_rate": lhit.rate if lhit else None,
                       "labour_cost": labour_cost, "handling_cost": handling,
                       "missing": missing, "complete": not missing})


async def sampling_price_for(db: AsyncSession, org_id: int, machine_class: str,
                             plant_id: Optional[int] = None, on_date: Optional[date] = None,
                             run_hours: Optional[float] = None) -> Optional[RateHit]:
    v = await version_on(db, org_id, on_date)
    return sampling_in_version(v, machine_class, plant_id, run_hours) if v else None


# ---------------------------------------------------------------- stale

async def stale_status(db: AsyncSession, org_id: int, today: Optional[date] = None) -> dict:
    """Whether Finance owes a review: the latest published version was last
    touched (the later of valid_from and published_at) more than
    cost_sheet_review_months ago, or nothing is published at all."""
    today = today or business_today()
    months = await review_months(db, org_id)
    latest = await latest_published(db, org_id)
    if latest is None:
        return {"stale": True, "review_months": months, "latest_version": None,
                "reviewed_on": None, "due_on": None, "reason": "no_published_version"}
    reviewed = max(latest.valid_from,
                   latest.published_at.date() if latest.published_at else latest.valid_from)
    due = add_months(reviewed, months)
    return {"stale": today >= due, "review_months": months, "latest_version": latest.version,
            "reviewed_on": reviewed.isoformat(), "due_on": due.isoformat(),
            "reason": "review_due" if today >= due else None}


# ---------------------------------------------------------------- serialization

def _rows(v: CostSheetVersion, section: str) -> list[dict]:
    _, cols = _ROW_COPY[section]
    return [{"id": r.id, **{c: (_f(getattr(r, c)) if c in _FLOAT_COLS else getattr(r, c))
                            for c in cols}}
            for r in getattr(v, _REL[section])]


_FLOAT_COLS = {"hourly_rate", "min_factor", "flat_price", "setup_hours", "run_hours_default",
               "labour_hours", "handling_cost", "value", "entered_rate"}


def version_summary(v: CostSheetVersion, valid: dict) -> dict:
    vf, vt = valid.get(v.id, (v.valid_from, None))
    return {"id": v.id, "version": v.version, "status": v.status,
            "valid_from": vf.isoformat() if vf else None,
            "valid_to": vt.isoformat() if vt else None,
            "note": v.note, "based_on_version_id": v.based_on_version_id,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "published_at": v.published_at.isoformat() if v.published_at else None,
            "published_by": v.published_by}


def version_detail(v: CostSheetVersion, valid: dict,
                   local_of: Optional[dict[int, str]] = None) -> dict:
    """The whole version. Department rates carry their effective rate
    (overhead applied at the row's own plant; None while the rate is empty);
    sampling rows their computed price. With local_of ({plant id: local
    currency}) rate and machine rows at a two-currency plant carry the rate
    in the local currency too (dual_view)."""
    rates = _rows(v, "rates")
    for r, row in zip(rates, v.rates):
        oh = _pick_overhead(v.overheads, row.department_id, row.plant_id)
        r["effective_rate"] = (None if row.hourly_rate is None
                               else apply_overhead(float(row.hourly_rate), oh, row.currency))
        r["overhead"] = _overhead_dict(oh)
    sampling = _rows(v, "sampling")
    for s, row in zip(sampling, v.sampling_rates):
        hit = sampling_in_version(
            v, row.machine_class_id if row.machine_class_id is not None else row.machine_class,
            row.plant_id)
        s["computed_price"] = hit.rate if hit and hit.row_id == row.id else None
        s["breakdown"] = hit.breakdown if hit and hit.row_id == row.id else None
    machines = _rows(v, "machines")
    for section_rows, models in ((rates, v.rates), (machines, v.machine_rates)):
        for r, row in zip(section_rows, models):
            r.update(dual_view(v, row, (local_of or {}).get(row.plant_id)))
    return {**version_summary(v, valid), "rates": rates,
            "machine_rates": machines, "sampling_rates": sampling,
            "overheads": _rows(v, "overheads"), "fx_rates": fx_list(v)}


# ---------------------------------------------------------------- diff

_DIFF_VALUES = {
    "rates": ("hourly_rate", "currency", "note", "entered_rate", "entered_currency"),
    "machines": ("hourly_rate", "currency", "tonnage_min", "tonnage_max", "note",
                 "entered_rate", "entered_currency"),
    "sampling": ("mode", "flat_price", "setup_hours", "run_hours_default", "labour_hours",
                 "labour_department_id", "labour_position", "handling_cost", "currency", "note"),
    "overheads": ("kind", "value", "currency", "note"),
    "machine_items": ("hourly_rate", "currency", "note", "entered_rate", "entered_currency"),
}
_DIFF_KEYS = {
    "rates": ("department_id", "plant_id"),
    "machines": ("plant_id", "machine_class", "machine_ref"),
    "sampling": ("plant_id", "machine_class"),
    "overheads": ("plant_id", "department_id"),
    "machine_items": ("machine_id",),
}


def diff_versions(old: Optional[CostSheetVersion], new: CostSheetVersion) -> dict:
    """Per section: added, removed and changed rows between two versions,
    keyed by what identifies a row (not its id, which differs per version)."""
    out: dict[str, Any] = {"from_version": old.version if old else None,
                           "from_version_id": old.id if old else None,
                           "to_version": new.version, "to_version_id": new.id}
    for section in SECTIONS:
        keys, vals = _DIFF_KEYS[section], _DIFF_VALUES[section]

        def index(v):
            if v is None:
                return {}
            res = {}
            for r in getattr(v, _REL[section]):
                k = tuple((getattr(r, c).casefold() if isinstance(getattr(r, c), str)
                           else getattr(r, c)) for c in keys)
                res[k] = r
            return res

        a, b = index(old), index(new)
        added, removed, changed = [], [], []

        def ident(r):
            return {c: getattr(r, c) for c in keys}

        def values(r):
            return {c: (_f(getattr(r, c)) if isinstance(getattr(r, c), float) else getattr(r, c))
                    for c in vals}

        for k, r in b.items():
            if k not in a:
                added.append({**ident(r), **values(r)})
            else:
                va, vb = values(a[k]), values(r)
                fields_changed = {c: {"old": va[c], "new": vb[c]} for c in vals if va[c] != vb[c]}
                if fields_changed:
                    # The row's currency (the new one when it changed) so a
                    # rate change reads "65.00 -> 70.00 USD", not a bare number.
                    entry = {**ident(r), "changes": fields_changed,
                             "currency": vb.get("currency")}
                    if ("hourly_rate" in fields_changed and va["hourly_rate"]
                            and vb["hourly_rate"] is not None):
                        entry["pct"] = round((vb["hourly_rate"] - va["hourly_rate"])
                                             / va["hourly_rate"] * 100, 1)
                    changed.append(entry)
        for k, r in a.items():
            if k not in b:
                removed.append({**ident(r), **values(r)})
        out[section] = {"added": added, "removed": removed, "changed": changed}
    before = {f["pair"]: f["rate"] for f in fx_list(old)} if old else {}
    after = {f["pair"]: f["rate"] for f in fx_list(new)}
    out["fx_rates"] = [{"pair": k, "old": before.get(k), "new": after.get(k)}
                       for k in sorted(set(before) | set(after))
                       if before.get(k) != after.get(k)]
    return out


def diff_is_empty(d: dict) -> bool:
    return (all(not (d[s]["added"] or d[s]["removed"] or d[s]["changed"]) for s in SECTIONS)
            and not d.get("fx_rates"))


async def previous_version(db: AsyncSession, v: CostSheetVersion) -> Optional[CostSheetVersion]:
    """The version a draft or published version is compared to: the one it
    was based on for a draft, the previous published one for a published."""
    if v.status == "draft" and v.based_on_version_id:
        return await db.get(CostSheetVersion, v.based_on_version_id)
    return (await db.execute(select(CostSheetVersion).where(
        CostSheetVersion.organization_id == v.organization_id,
        CostSheetVersion.status == "published",
        CostSheetVersion.version < v.version,
    ).order_by(CostSheetVersion.version.desc()).limit(1))).scalar_one_or_none()


# ---------------------------------------------------------------- export

async def _names(db: AsyncSession, org_id: int) -> tuple[dict, dict]:
    deps = dict((await db.execute(select(Department.id, Department.name))).all())
    plants = dict((await db.execute(select(Plant.id, Plant.name).where(
        Plant.organization_id == org_id))).all())
    return deps, plants


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe(value):
    """Neutralise spreadsheet formulas: a text cell starting with = + - @ tab
    or CR is prefixed with ' so Excel and LibreOffice show it as text instead
    of running it (CSV/formula injection). Numbers pass unchanged."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


async def _machine_names(db: AsyncSession, org_id: int) -> dict[int, tuple]:
    """{machine id: (name, plant id, tonnage)} of the synced MachineDB presses."""
    from app.models.cost_sheet_machines import CostSheetMachine
    return {mid: (name, pid, t) for mid, name, pid, t in (await db.execute(
        select(CostSheetMachine.id, CostSheetMachine.internal_name, CostSheetMachine.plant_id,
               CostSheetMachine.clamping_force_t).where(
            CostSheetMachine.organization_id == org_id))).all()}


def _export_tables(v: CostSheetVersion, deps: dict, plants: dict,
                   machines: Optional[dict] = None) -> dict[str, tuple[list, list]]:
    """Header and rows per sheet. Text goes through _safe; numbers stay numbers."""
    detail = version_detail(v, {})
    pl = lambda i: plants.get(i, "") if i else "All plants"  # noqa: E731
    dp = lambda i: deps.get(i, "") if i else "All departments"  # noqa: E731
    tables = {
        "Rates": (["Department", "Plant", "Hourly rate", "Effective rate",
                   "Currency", "Note"],
                  [[dp(r["department_id"]), pl(r["plant_id"]),
                    r["hourly_rate"], r["effective_rate"], r["currency"], r["note"] or ""]
                   for r in detail["rates"]]),
        "Machines": (["Machine class", "Machine", "Plant", "Tonnage min", "Tonnage max",
                      "Hourly rate", "Currency", "Note"],
                     [[r["machine_class"], r["machine_ref"] or "", pl(r["plant_id"]),
                       r["tonnage_min"], r["tonnage_max"], r["hourly_rate"], r["currency"],
                       r["note"] or ""] for r in detail["machine_rates"]]),
        "Sampling": (["Machine class", "Plant", "Mode", "Flat price", "Setup h", "Run h",
                      "Labour h", "Labour department", "Handling",
                      "Price per trial", "Currency", "Note"],
                     [[r["machine_class"], pl(r["plant_id"]), r["mode"], r["flat_price"],
                       r["setup_hours"], r["run_hours_default"], r["labour_hours"],
                       deps.get(r["labour_department_id"], "") if r["labour_department_id"] else "",
                       r["handling_cost"], r["computed_price"],
                       r["currency"], r["note"] or ""]
                      for r in detail["sampling_rates"]]),
        "Overheads": (["Department", "Plant", "Kind", "Value", "Currency", "Note"],
                      [[dp(r["department_id"]), pl(r["plant_id"]),
                        "Percent" if r["kind"] == "percent" else "Per hour", r["value"],
                        r["currency"] or "", r["note"] or ""] for r in detail["overheads"]]),
    }
    # Own rates of MachineDB presses (105/107), by plant and machine name.
    machines = machines or {}
    items = sorted(v.machine_item_rates, key=lambda r: (
        pl(machines.get(r.machine_id, (None, None, None))[1]),
        machines.get(r.machine_id, (f"Machine {r.machine_id}",))[0] or ""))
    tables["Machine rates"] = (
        ["Machine", "Plant", "Tonnage t", "Hourly rate", "Currency",
         "Typed rate", "Typed currency", "Note"],
        [[machines.get(r.machine_id, (f"Machine {r.machine_id}",))[0],
          pl(machines.get(r.machine_id, (None, None, None))[1]),
          _f(machines.get(r.machine_id, (None, None, None))[2]),
          _f(r.hourly_rate), r.currency,
          _f(r.entered_rate) if r.entered_currency else None,
          r.entered_currency or "", r.note or ""] for r in items])
    return {k: (head, [[_safe(c) for c in row] for row in rows])
            for k, (head, rows) in tables.items()}


def _csv_number(value: float, full: bool) -> str:
    """German Excel reads ';'-separated CSV with a decimal comma."""
    text = (f"{value:.4f}".rstrip("0").rstrip(".") if full else f"{value:.2f}")
    return text.replace(".", ",")


async def export_csv(db: AsyncSession, v: CostSheetVersion, section: str = "Rates") -> str:
    deps, plants = await _names(db, v.organization_id)
    tables = _export_tables(v, deps, plants, await _machine_names(db, v.organization_id))
    # "Positions" is the tab's old name (links and bookmarks keep working)
    section = {"Positions": "Rates", "MachineRates": "Machine rates"}.get(section, section)
    head, rows = tables.get(section, tables["Rates"])
    # overhead values keep their full precision (12.5 %, 0.25 per hour)
    full = {i for i, h in enumerate(head) if section == "Overheads" and h == "Value"}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(head)
    for r in rows:
        w.writerow(["" if c is None
                    else _csv_number(float(c), i in full) if isinstance(c, float)
                    else c for i, c in enumerate(r)])
    return buf.getvalue()


async def export_xlsx(db: AsyncSession, v: CostSheetVersion) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    deps, plants = await _names(db, v.organization_id)
    wb = Workbook()
    wb.remove(wb.active)
    valid = validity(await list_versions(db, v.organization_id))
    vf, vt = valid.get(v.id, (v.valid_from, None))
    for title, (head, rows) in _export_tables(
            v, deps, plants, await _machine_names(db, v.organization_id)).items():
        ws = wb.create_sheet(title)
        ws.append([f"Cost sheet version {v.version} ({v.status})",
                   f"Valid from {vf.isoformat() if vf else '-'}",
                   f"Valid to {vt.isoformat() if vt else 'open'}"])
        ws.append([])
        ws.append(head)
        for c in ws[3]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append(r)
        for col in ws.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 40)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- legacy shape

async def reference_rates(db: AsyncSession, org_id: int,
                          on_date: Optional[date] = None) -> Optional[list[dict]]:
    """Rates of the currently valid version in the legacy
    /changes/reference/rates shape ({department_id, plant_id, hourly_rate,
    min_factor}): rows with a rate, plant-wide rows expanded to every active
    plant that has no own rate. None when nothing is published yet (the
    caller then falls back to department_rate)."""
    v = await version_on(db, org_id, on_date)
    if v is None:
        return None
    plant_ids = [p for (p,) in (await db.execute(select(Plant.id).where(
        Plant.organization_id == org_id, Plant.is_active.is_(True)))).all()]
    out: dict[tuple[int, int], dict] = {}
    defaults = [r for r in v.rates if r.hourly_rate is not None]
    for r in defaults:
        if r.plant_id is not None:
            out[(r.department_id, r.plant_id)] = {
                "department_id": r.department_id, "plant_id": r.plant_id,
                "hourly_rate": float(r.hourly_rate),
                "min_factor": r.min_factor if r.min_factor is not None else 1.0}
    for r in defaults:
        if r.plant_id is None:
            for pid in plant_ids:
                out.setdefault((r.department_id, pid), {
                    "department_id": r.department_id, "plant_id": pid,
                    "hourly_rate": float(r.hourly_rate),
                    "min_factor": r.min_factor if r.min_factor is not None else 1.0})
    return list(out.values())


# ---------------------------------------------------------------- exchange rates
#
# A version carries the exchange rates it uses (106): {"USD/MXN": "17.30"} =
# one USD is 17.30 MXN, kept as the decimal text typed. A plant with a local
# currency (Silao: quote USD, local MXN) shows each rate in both; the rate
# may be typed in either. Typed in the local currency, the typed number is
# kept (entered_rate, entered_currency) and hourly_rate (the quote currency,
# which costing reads) is computed from it, so the typed number never drifts.

FX_MAX = Decimal("1000000")
CENT = Decimal("0.01")


def _pair(base: str, quote: str) -> str:
    return f"{base}/{quote}"


def _money(d: Decimal) -> float:
    return float(d.quantize(CENT, rounding=ROUND_HALF_UP))


def fx_rate(v: Optional[CostSheetVersion], base: str, quote: str) -> Optional[Decimal]:
    """Units of `quote` for one `base` in v (the inverse pair counts too);
    None when the version has no such rate."""
    if not base or not quote:
        return None
    if base == quote:
        return Decimal(1)
    rates = (v.fx_rates or {}) if v is not None else {}
    raw = rates.get(_pair(base, quote))
    if raw not in (None, ""):
        return Decimal(str(raw))
    inv = rates.get(_pair(quote, base))
    if inv not in (None, ""):
        return Decimal(1) / Decimal(str(inv))
    return None


def convert(v: Optional[CostSheetVersion], amount, from_cur: str,
            to_cur: str) -> Optional[float]:
    """amount in from_cur expressed in to_cur at v's rate (cents, half up);
    None without a rate. Never guessed."""
    if amount is None:
        return None
    rate = fx_rate(v, to_cur, from_cur)       # units of from_cur per one to_cur
    if rate is None or rate == 0:
        return None
    return _money(Decimal(str(amount)) / rate)


def fx_list(v: Optional[CostSheetVersion]) -> list[dict]:
    """[{pair, base, quote, rate}] in pair order; rate is the decimal text."""
    if v is None or not v.fx_rates:
        return []
    out = []
    for pair in sorted(v.fx_rates):
        base, _, quote = pair.partition("/")
        out.append({"pair": pair, "base": base, "quote": quote,
                    "rate": str(v.fx_rates[pair])})
    return out


def _parse_fx(value) -> Decimal:
    try:
        d = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise CostSheetError("The exchange rate must be a number", 422)
    if not d.is_finite() or d <= 0 or d >= FX_MAX:
        raise CostSheetError("The exchange rate must be above 0 and below 1,000,000", 422)
    return d


def _from_entered(v: CostSheetVersion, entered, row_currency: str,
                  entered_currency: str) -> Optional[float]:
    """The row's hourly_rate (row currency) for a rate typed in
    entered_currency; None without the exchange rate."""
    rate = fx_rate(v, row_currency, entered_currency)
    if rate is None or rate == 0:
        return None
    return _money(Decimal(str(entered)) / rate)


async def set_fx_rate(db: AsyncSession, v: CostSheetVersion, base: str, quote: str,
                      rate) -> CostSheetVersion:
    """Set (rate None: remove) one exchange rate of a draft, then re-price
    every row typed in another currency from its typed number."""
    _require_draft(v)
    base, quote = normalize_currency(base), normalize_currency(quote)
    if base == quote:
        raise CostSheetError("An exchange rate needs two different currencies", 422)
    rates = dict(v.fx_rates or {})
    rates.pop(_pair(quote, base), None)        # one direction per pair
    d = None
    if rate is None or str(rate).strip() == "":
        rates.pop(_pair(base, quote), None)
    else:
        d = _parse_fx(rate)
        _check_plausible(base, quote, d)
        rates[_pair(base, quote)] = format(d, "f")     # the number as typed
    old_rates = v.fx_rates
    v.fx_rates = rates or None
    await db.refresh(v, ["rates", "machine_rates", "machine_item_rates"])
    # re-price first, check every row, and only then write: a rate that
    # takes a row out of bounds is refused with nothing changed
    new_hourly = []
    for row in list(v.rates) + list(v.machine_rates) + list(v.machine_item_rates):
        if row.entered_currency and row.entered_currency != row.currency \
                and row.entered_rate is not None:
            hourly = _from_entered(v, row.entered_rate, row.currency,
                                   row.entered_currency)
            # machine rows cannot hold an empty rate: without the exchange
            # rate they keep the last number (publish refuses them anyway)
            if hourly is None and not isinstance(row, CostSheetRate):
                continue
            if hourly is not None:
                try:
                    _check_number("hourly_rate", hourly, *BOUNDS["hourly_rate"])
                except CostSheetError:
                    v.fx_rates = old_rates
                    said = (f"At 1 {base} = {format(d, 'f')} {quote}" if d is not None
                            else "With these exchange rates")
                    raise CostSheetError(
                        f"{said} the rate typed as "
                        f"{row.entered_rate:,.2f} {row.entered_currency} would be "
                        f"{hourly:,.2f} {row.currency}, out of range. Check the "
                        "exchange rate and its direction", 422)
            new_hourly.append((row, hourly))
    for row, hourly in new_hourly:
        row.hourly_rate = hourly
    await db.flush()
    return v


# Plausible exchange rates, as units of the second currency for one of the
# first (either direction is checked). A rate outside is refused: it is
# most likely typed the wrong way round (1 MXN = 17.30 USD) or a typo.
FX_PLAUSIBLE = {
    ("USD", "MXN"): (Decimal("5"), Decimal("50")),
    ("EUR", "MXN"): (Decimal("5"), Decimal("50")),
    ("EUR", "USD"): (Decimal("0.5"), Decimal("2")),
}


def _check_plausible(base: str, quote: str, rate: Decimal) -> None:
    """Refuse an implausible rate for a known pair, naming the direction."""
    if (base, quote) in FX_PLAUSIBLE:
        lo, hi = FX_PLAUSIBLE[(base, quote)]
        per, one, r = quote, base, rate
    elif (quote, base) in FX_PLAUSIBLE:
        lo, hi = FX_PLAUSIBLE[(quote, base)]
        per, one, r = base, quote, Decimal(1) / rate
    else:
        return
    if not lo <= r <= hi:
        raise CostSheetError(
            f"1 {base} = {format(rate, 'f')} {quote} is not a plausible exchange rate: "
            f"1 {one} is expected to be between {lo} and {hi} {per}. "
            "Check the direction", 422)


async def _apply_entered(db: AsyncSession, v: CostSheetVersion, section: str, data: dict,
                         changed: set) -> None:
    """Rates and machine rows: a rate typed in the plant's local currency
    (entered_rate + entered_currency) sets hourly_rate from the version's
    exchange rate; a rate typed as hourly_rate clears the typed local one; a
    move to another plant or currency re-prices from the typed number."""
    if section not in ("rates", "machines"):
        return
    cur = normalize_currency(data.get("currency") or "EUR")
    if "entered_rate" in changed:
        entered = data.get("entered_rate")
        ecur = data.get("entered_currency") or cur
        ecur = normalize_currency(ecur)
        if entered is None:
            data["hourly_rate"] = None
            data["entered_rate"] = data["entered_currency"] = None
            return
        entered = _check_number("entered_rate", entered, 0, 1e10)
        if ecur == cur:
            data["hourly_rate"] = entered
            data["entered_rate"] = data["entered_currency"] = None
            return
        data["entered_rate"], data["entered_currency"] = entered, ecur
    elif "hourly_rate" in changed:
        data["entered_rate"] = data["entered_currency"] = None
        return
    ecur = data.get("entered_currency")
    if not ecur or data.get("entered_rate") is None or ecur == cur:
        if ecur == cur:
            data["entered_rate"] = data["entered_currency"] = None
        return
    plant = await db.get(Plant, data["plant_id"]) if data.get("plant_id") else None
    if plant is None or plant.local_currency != ecur:
        raise CostSheetError(
            f"{ecur} is not the local currency of this row's plant: type the rate in "
            f"{cur}", 422)
    quote = plant.currency or "EUR"
    if cur != quote:
        # the local rate converts into the plant's quote currency only: a
        # row still in another currency is switched first (by the user)
        raise CostSheetError(
            f"This row is in {cur}, not {plant.name}'s quote currency {quote}: switch "
            f"the row to {quote} first, then type the rate in {ecur}", 422)
    hourly = _from_entered(v, data["entered_rate"], cur, ecur)
    if hourly is None:
        raise CostSheetError(
            f"Enter the {cur}/{ecur} exchange rate of this version first", 422)
    data["hourly_rate"] = hourly


def dual_view(v: CostSheetVersion, row, local: Optional[str]) -> dict:
    """What a two-currency plant's row shows besides its own rate: the rate
    in the local currency (the typed number when it was typed there, else
    converted at the version's rate) and which of the two was typed."""
    if not local or local == row.currency:
        return {"local_currency": None, "local_rate": None, "entered_in": None}
    typed_local = row.entered_currency == local and row.entered_rate is not None
    if typed_local:
        local_rate = float(row.entered_rate)
    elif row.hourly_rate is None:
        local_rate = None
    else:
        rate = fx_rate(v, row.currency, local)
        local_rate = (None if rate is None
                      else _money(Decimal(str(row.hourly_rate)) * rate))
    return {"local_currency": local, "local_rate": local_rate,
            "entered_in": ("local" if typed_local
                           else ("quote" if row.hourly_rate is not None else None))}


async def local_currencies(db: AsyncSession, org_id: int) -> dict[int, str]:
    """{plant id: local currency} for the org's plants that have one."""
    return {pid: cur for pid, cur in (await db.execute(
        select(Plant.id, Plant.local_currency).where(
            Plant.organization_id == org_id, Plant.local_currency.is_not(None)))).all()}


async def fx_needed(db: AsyncSession, org_id: int) -> list[dict]:
    """The exchange rates the sheet needs: quote/local of every active plant
    with a local currency (one per pair)."""
    rows = (await db.execute(select(Plant.currency, Plant.local_currency).where(
        Plant.organization_id == org_id, Plant.is_active.is_(True),
        Plant.local_currency.is_not(None)))).all()
    pairs = sorted({(q or "EUR", loc) for q, loc in rows if loc and loc != (q or "EUR")})
    return [{"pair": _pair(b, q), "base": b, "quote": q} for b, q in pairs]


async def version_detail_full(db: AsyncSession, v: CostSheetVersion, valid: dict) -> dict:
    """version_detail with the two-currency view, the exchange rates the
    org's plants need and the rows whose currency is not their plant's
    quote currency (currency_mismatch)."""
    detail = version_detail(v, valid, await local_currencies(db, v.organization_id))
    detail["fx_needed"] = await fx_needed(db, v.organization_id)
    detail["currency_mismatch"] = await currency_mismatch(db, v)
    return detail


async def currency_mismatch(db: AsyncSession, v: CostSheetVersion) -> list[dict]:
    """Rows with a rate at one plant whose currency is not that plant's
    quote currency (a row copied before the plant's currency changed, e.g.
    Silao before its currency decision). Flagged in the draft and the
    publish dialog, never relabelled: the number was typed in the row's
    currency. [{section, row_id, plant_id, plant_name, currency,
    plant_currency}]"""
    from app.models.cost_sheet_machines import CostSheetMachine
    plants = {p.id: p for p in (await db.execute(select(Plant).where(
        Plant.organization_id == v.organization_id))).scalars().all()}
    machine_plant = {}
    if v.machine_item_rates:
        machine_plant = dict((await db.execute(select(
            CostSheetMachine.id, CostSheetMachine.plant_id).where(CostSheetMachine.id.in_(
                {r.machine_id for r in v.machine_item_rates})))).all())
    out = []
    checks = [("rates", r, r.plant_id, r.hourly_rate) for r in v.rates] \
        + [("machines", r, r.plant_id, r.hourly_rate) for r in v.machine_rates] \
        + [("sampling", r, r.plant_id, True) for r in v.sampling_rates] \
        + [("overheads", r, r.plant_id, True) for r in v.overheads
           if r.kind != "percent"] \
        + [("machine_items", r, machine_plant.get(r.machine_id), r.hourly_rate)
           for r in v.machine_item_rates]
    for section, row, plant_id, value in checks:
        plant = plants.get(plant_id) if plant_id is not None else None
        if plant is None or value is None or not row.currency:
            continue
        quote = plant.currency or "EUR"
        if row.currency != quote:
            out.append({"section": section, "row_id": row.id, "plant_id": plant_id,
                        "plant_name": plant.name, "currency": row.currency,
                        "plant_currency": quote})
    return out


# ---------------------------------------------------------------- plant currencies

async def plant_currencies(db: AsyncSession, org_id: int) -> list[dict]:
    """Every plant with its currency and whether Finance confirmed it
    (migration 094 set it from the location only)."""
    plants = (await db.execute(select(Plant).where(Plant.organization_id == org_id)
                               .order_by(Plant.name))).scalars().all()
    confirmed = {k for (k,) in (await db.execute(select(OrgSetting.key).where(
        OrgSetting.organization_id == org_id,
        OrgSetting.key.like(SETTING_PLANT_CURRENCY_CONFIRMED + "%"),
        OrgSetting.value == "1"))).all()}
    return [{"id": p.id, "name": p.name, "code": p.code, "is_active": p.is_active,
             "currency": p.currency or "EUR", "local_currency": p.local_currency,
             "currency_confirmed": f"{SETTING_PLANT_CURRENCY_CONFIRMED}{p.id}" in confirmed}
            for p in plants]


async def set_plant_currency(db: AsyncSession, org_id: int, plant_id: int, currency: str,
                             user_id: Optional[int], *, local_currency=...) -> None:
    """Sales or Finance sets (or confirms) a plant's quote currency and,
    optionally, its local currency (None: one currency only). Existing rows
    keep theirs: a published price does not change its code after the fact."""
    plant = await db.get(Plant, plant_id)
    if plant is None or plant.organization_id != org_id:
        raise CostSheetError("Unknown plant", 404)
    plant.currency = normalize_currency(currency)
    if local_currency is not ...:
        local = normalize_currency(local_currency) if local_currency else None
        plant.local_currency = None if local == plant.currency else local
    await set_setting(db, org_id, f"{SETTING_PLANT_CURRENCY_CONFIRMED}{plant_id}", "1", user_id)
    await db.flush()
