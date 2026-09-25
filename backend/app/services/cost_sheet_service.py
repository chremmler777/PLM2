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
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cost_sheet import (
    CostSheetVersion, CostSheetRate, CostSheetMachineRate, CostSheetMachineClass,
    CostSheetSamplingRate, CostSheetOverhead, OrgSetting,
    OVERHEAD_KINDS, SAMPLING_MODES, FINANCE_DEPARTMENT, DEFAULT_REVIEW_MONTHS,
    SETTING_REVIEW_MONTHS,
)
from app.models.entities import Plant
from app.models.workflow import Department


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


async def can_edit(db: AsyncSession, user) -> bool:
    """Finance members or admins. Acts-as aware: an admin acting as a
    department is that department only (spec D2), so acting as Finance may
    edit and acting as anything else may not."""
    from app.services.workflow_service import WorkflowService
    if getattr(user, "acts_as_department_id", None) is None and user.role == "admin":
        return True
    fin = await finance_department_id(db)
    if fin is None:
        return False
    return fin in await WorkflowService.effective_department_ids(db, user)


async def require_edit(db: AsyncSession, user) -> None:
    if not await can_edit(db, user):
        raise CostSheetError("Only Finance or an admin may edit the cost sheet", 403)


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
    on_date = on_date or date.today()
    return (await db.execute(select(CostSheetVersion).where(
        CostSheetVersion.organization_id == org_id,
        CostSheetVersion.status == "published",
        CostSheetVersion.valid_from <= on_date,
    ).order_by(CostSheetVersion.valid_from.desc(),
               CostSheetVersion.version.desc()).limit(1))).scalar_one_or_none()


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
                              "currency", "min_factor", "note")),
    "machines": (CostSheetMachineRate, ("plant_id", "machine_class", "machine_ref",
                                        "tonnage_min", "tonnage_max", "hourly_rate",
                                        "currency", "note")),
    "sampling": (CostSheetSamplingRate, ("plant_id", "machine_class", "mode", "flat_price",
                                         "setup_hours", "run_hours_default", "labour_hours",
                                         "labour_department_id", "labour_position",
                                         "handling_cost", "currency", "note")),
    "overheads": (CostSheetOverhead, ("plant_id", "department_id", "kind", "value", "note")),
}
_REL = {"rates": "rates", "machines": "machine_rates", "sampling": "sampling_rates",
        "overheads": "overheads"}
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
    draft = CostSheetVersion(organization_id=org_id, version=nxt, status="draft",
                             based_on_version_id=base.id if base else None,
                             created_by=user_id, created_at=datetime.utcnow())
    db.add(draft)
    await db.flush()
    if base is not None:
        for section, (model, cols) in _ROW_COPY.items():
            for row in getattr(base, _REL[section]):
                db.add(model(version_id=draft.id, **{c: getattr(row, c) for c in cols}))
        await db.flush()
    await db.refresh(draft)
    return draft


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
                  valid_from: date, note: Optional[str] = None) -> CostSheetVersion:
    """Freeze a draft. valid_from must lie after the latest published
    version's, which then ends the day before."""
    _require_draft(v)
    latest = await latest_published(db, v.organization_id)
    if latest is not None and valid_from <= latest.valid_from:
        raise CostSheetError(
            f"Valid from must be after {latest.valid_from.isoformat()} "
            f"(version {latest.version})", 422)
    if not v.rates:
        raise CostSheetError("A version needs at least one position rate", 422)
    v.valid_from = valid_from
    if note is not None:
        v.note = note
    v.status = "published"
    v.published_at = datetime.utcnow()
    v.published_by = user_id
    await db.flush()
    return v


# ---------------------------------------------------------------- row edits

_ROW_NUMERIC_NONNEG = {"hourly_rate", "flat_price", "setup_hours", "run_hours_default",
                       "labour_hours", "handling_cost", "min_factor"}


async def _validate_row(db: AsyncSession, org_id: int, section: str, data: dict) -> None:
    for k in _ROW_NUMERIC_NONNEG:
        if data.get(k) is not None and float(data[k]) < 0:
            raise CostSheetError(f"{k} must not be negative", 422)
    if data.get("plant_id") is not None:
        plant = await db.get(Plant, data["plant_id"])
        if plant is None or plant.organization_id != org_id:
            raise CostSheetError("Unknown plant", 422)
    for key in ("department_id", "labour_department_id"):
        if data.get(key) is not None and await db.get(Department, data[key]) is None:
            raise CostSheetError("Unknown department", 422)
    if "currency" in data and data["currency"] is not None:
        cur = str(data["currency"]).strip().upper()
        if len(cur) != 3 or not cur.isalpha():
            raise CostSheetError("Currency is a 3-letter code", 422)
        data["currency"] = cur
    for key in ("position", "labour_position", "machine_ref", "machine_class"):
        if key in data:
            data[key] = _norm_position(data[key])
    if section == "rates":
        if data.get("department_id") is None:
            raise CostSheetError("A rate needs a department", 422)
        if data.get("hourly_rate") is None:
            raise CostSheetError("A rate needs an hourly rate", 422)
    if section in ("machines", "sampling") and not data.get("machine_class"):
        raise CostSheetError("A machine class is required", 422)
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


def _duplicate_key(section: str, data: dict) -> tuple:
    """What identifies a row within a version; text compares case-blind,
    the same way the lookups match."""
    key = _raw_key(section, data)
    return tuple(k.casefold() if isinstance(k, str) else k for k in key)


def _raw_key(section: str, data: dict) -> tuple:
    if section == "rates":
        return (data.get("department_id"), data.get("position"), data.get("plant_id"))
    if section == "machines":
        return (data.get("plant_id"), data.get("machine_class"), data.get("machine_ref"))
    if section == "sampling":
        return (data.get("plant_id"), data.get("machine_class"))
    return (data.get("plant_id"), data.get("department_id"))


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
    await _validate_row(db, v.organization_id, section, data)
    _check_unique(v, section, data)
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
    merged.update({k: val for k, val in changes.items() if k in cols})
    if "currency" in merged and not merged["currency"]:
        merged["currency"] = "EUR"
    await _validate_row(db, v.organization_id, section, merged)
    _check_unique(v, section, merged, exclude_id=row.id)
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
    rate: float
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
    """dept+position+plant > dept+position > dept+plant > dept."""
    position = _norm_position(position)
    pos_key = position.casefold() if position else None
    order = []
    if pos_key is not None:
        order += [(pos_key, plant_id, "department+position+plant"),
                  (pos_key, None, "department+position")]
    order += [(None, plant_id, "department+plant"), (None, None, "department")]
    cands = [r for r in rows if r.department_id == department_id]
    for pk, pl, label in order:
        if pl is None and label.endswith("plant"):
            continue
        for r in cands:
            rp = r.position.casefold() if r.position else None
            if rp == pk and r.plant_id == pl:
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


def apply_overhead(base: float, oh: Optional[CostSheetOverhead]) -> float:
    if oh is None:
        return round(base, 2)
    if oh.kind == "percent":
        return round(base * (1 + float(oh.value) / 100.0), 2)
    return round(base + float(oh.value), 2)


def _overhead_dict(oh: Optional[CostSheetOverhead]) -> Optional[dict]:
    if oh is None:
        return None
    return {"id": oh.id, "kind": oh.kind, "value": float(oh.value),
            "department_id": oh.department_id, "plant_id": oh.plant_id}


def rate_in_version(v: CostSheetVersion, department_id: int, position: Optional[str],
                    plant_id: Optional[int], *, with_overhead: bool = False) -> Optional[RateHit]:
    row, match = _pick_rate(v.rates, department_id, position, plant_id)
    if row is None:
        return None
    base = float(row.hourly_rate)
    hit = RateHit(rate=round(base, 2), currency=row.currency, version_id=v.id,
                  version=v.version, row_id=row.id, match=match, base_rate=round(base, 2))
    if with_overhead:
        oh = _pick_overhead(v.overheads, department_id, plant_id)
        hit.rate = apply_overhead(base, oh)
        hit.overhead = _overhead_dict(oh)
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


def _pick_machine(rows: Iterable[CostSheetMachineRate], machine_class: str,
                  plant_id: Optional[int], machine_ref: Optional[str]):
    """ref+plant > ref > class+plant > class (class rows have no ref)."""
    mc = machine_class.casefold()
    ref = _norm_position(machine_ref)
    rows = [r for r in rows if r.machine_class.casefold() == mc]
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
    mc = machine_class.casefold()
    rows = [r for r in v.sampling_rates if r.machine_class.casefold() == mc]
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
    mhit = machine_rate_in_version(v, row.machine_class, plant_id)
    machine_cost = round((setup + run) * mhit.rate, 2) if mhit else 0.0
    labour_hours = float(row.labour_hours or 0)
    lhit = None
    if labour_hours and row.labour_department_id:
        lhit = rate_in_version(v, row.labour_department_id, row.labour_position, plant_id,
                               with_overhead=True)
    labour_cost = round(labour_hours * lhit.rate, 2) if lhit else 0.0
    handling = float(row.handling_cost or 0)
    missing = []
    if (setup + run) and mhit is None:
        missing.append("machine_rate")
    if labour_hours and lhit is None:
        missing.append("labour_rate")
    price = round(machine_cost + labour_cost + handling, 2)
    return RateHit(rate=price, currency=row.currency, version_id=v.id, version=v.version,
                   row_id=row.id, match=match, breakdown={
                       "mode": "components", "setup_hours": setup, "run_hours": run,
                       "machine_rate": mhit.rate if mhit else None, "machine_cost": machine_cost,
                       "labour_hours": labour_hours, "labour_rate": lhit.rate if lhit else None,
                       "labour_cost": labour_cost, "handling_cost": handling,
                       "missing": missing})


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
    today = today or date.today()
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
               "labour_hours", "handling_cost", "value"}


def version_summary(v: CostSheetVersion, valid: dict) -> dict:
    vf, vt = valid.get(v.id, (v.valid_from, None))
    return {"id": v.id, "version": v.version, "status": v.status,
            "valid_from": vf.isoformat() if vf else None,
            "valid_to": vt.isoformat() if vt else None,
            "note": v.note, "based_on_version_id": v.based_on_version_id,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "published_at": v.published_at.isoformat() if v.published_at else None,
            "published_by": v.published_by}


def version_detail(v: CostSheetVersion, valid: dict) -> dict:
    """The whole version. Positions carry their effective rate (overhead
    applied at the row's own plant); sampling rows their computed price."""
    rates = _rows(v, "rates")
    for r, row in zip(rates, v.rates):
        oh = _pick_overhead(v.overheads, row.department_id, row.plant_id)
        r["effective_rate"] = apply_overhead(float(row.hourly_rate), oh)
        r["overhead"] = _overhead_dict(oh)
    sampling = _rows(v, "sampling")
    for s, row in zip(sampling, v.sampling_rates):
        hit = sampling_in_version(v, row.machine_class, row.plant_id)
        s["computed_price"] = hit.rate if hit and hit.row_id == row.id else None
        s["breakdown"] = hit.breakdown if hit and hit.row_id == row.id else None
    return {**version_summary(v, valid), "rates": rates,
            "machine_rates": _rows(v, "machines"), "sampling_rates": sampling,
            "overheads": _rows(v, "overheads")}


# ---------------------------------------------------------------- diff

_DIFF_VALUES = {
    "rates": ("hourly_rate", "currency", "note"),
    "machines": ("hourly_rate", "currency", "tonnage_min", "tonnage_max", "note"),
    "sampling": ("mode", "flat_price", "setup_hours", "run_hours_default", "labour_hours",
                 "labour_department_id", "labour_position", "handling_cost", "currency", "note"),
    "overheads": ("kind", "value", "note"),
}
_DIFF_KEYS = {
    "rates": ("department_id", "position", "plant_id"),
    "machines": ("plant_id", "machine_class", "machine_ref"),
    "sampling": ("plant_id", "machine_class"),
    "overheads": ("plant_id", "department_id"),
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
                    entry = {**ident(r), "changes": fields_changed}
                    if "hourly_rate" in fields_changed and va["hourly_rate"]:
                        entry["pct"] = round((vb["hourly_rate"] - va["hourly_rate"])
                                             / va["hourly_rate"] * 100, 1)
                    changed.append(entry)
        for k, r in a.items():
            if k not in b:
                removed.append({**ident(r), **values(r)})
        out[section] = {"added": added, "removed": removed, "changed": changed}
    return out


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


def _export_tables(v: CostSheetVersion, deps: dict, plants: dict) -> dict[str, tuple[list, list]]:
    detail = version_detail(v, {})
    pl = lambda i: plants.get(i, "") if i else "All plants"  # noqa: E731
    dp = lambda i: deps.get(i, "") if i else "All departments"  # noqa: E731
    return {
        "Positions": (["Department", "Position", "Plant", "Hourly rate", "Effective rate",
                       "Currency", "Note"],
                      [[dp(r["department_id"]), r["position"] or "Default", pl(r["plant_id"]),
                        r["hourly_rate"], r["effective_rate"], r["currency"], r["note"] or ""]
                       for r in detail["rates"]]),
        "Machines": (["Machine class", "Machine", "Plant", "Tonnage min", "Tonnage max",
                      "Hourly rate", "Currency", "Note"],
                     [[r["machine_class"], r["machine_ref"] or "", pl(r["plant_id"]),
                       r["tonnage_min"], r["tonnage_max"], r["hourly_rate"], r["currency"],
                       r["note"] or ""] for r in detail["machine_rates"]]),
        "Sampling": (["Machine class", "Plant", "Mode", "Flat price", "Setup h", "Run h",
                      "Labour h", "Labour department", "Handling", "Price per trial",
                      "Currency", "Note"],
                     [[r["machine_class"], pl(r["plant_id"]), r["mode"], r["flat_price"],
                       r["setup_hours"], r["run_hours_default"], r["labour_hours"],
                       deps.get(r["labour_department_id"], "") if r["labour_department_id"] else "",
                       r["handling_cost"], r["computed_price"], r["currency"], r["note"] or ""]
                      for r in detail["sampling_rates"]]),
        "Overheads": (["Department", "Plant", "Kind", "Value", "Note"],
                      [[dp(r["department_id"]), pl(r["plant_id"]),
                        "Percent" if r["kind"] == "percent" else "Per hour", r["value"],
                        r["note"] or ""] for r in detail["overheads"]]),
    }


async def export_csv(db: AsyncSession, v: CostSheetVersion, section: str = "Positions") -> str:
    deps, plants = await _names(db, v.organization_id)
    tables = _export_tables(v, deps, plants)
    head, rows = tables.get(section, tables["Positions"])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(head)
    for r in rows:
        w.writerow(["" if c is None else f"{c:.2f}" if isinstance(c, float) else c
                    for c in r])
    return buf.getvalue()


async def export_xlsx(db: AsyncSession, v: CostSheetVersion) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    deps, plants = await _names(db, v.organization_id)
    wb = Workbook()
    wb.remove(wb.active)
    valid = validity(await list_versions(db, v.organization_id))
    vf, vt = valid.get(v.id, (v.valid_from, None))
    for title, (head, rows) in _export_tables(v, deps, plants).items():
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
    min_factor}): department defaults only (position None), plant-wide rows
    expanded to every active plant that has no own row. None when nothing is
    published yet (the caller then falls back to department_rate)."""
    v = await version_on(db, org_id, on_date)
    if v is None:
        return None
    plant_ids = [p for (p,) in (await db.execute(select(Plant.id).where(
        Plant.organization_id == org_id, Plant.is_active.is_(True)))).all()]
    out: dict[tuple[int, int], dict] = {}
    defaults = [r for r in v.rates if r.position is None]
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
