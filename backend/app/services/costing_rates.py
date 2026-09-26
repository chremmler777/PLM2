"""Costing priced from the Finance cost sheet (spec §15 phase 2).

One place that answers "what is an hour (a machine hour, a trial) of this
worth on this change, and where does the number come from":

- labour hours: `cost_sheet_service.effective_labour_rate` (department +
  optional position + the costing plant, on the costing date);
- machine_time lines: the machine class rate; sampling lines: the price of
  one trial of the class;
- the legacy `department_rate` table only when the organisation has no
  published cost sheet version at all.

A Price with rate None means "cannot price": the line shows "No rate in the
cost sheet" and is never counted as 0. The currency is the costing plant's
(the rate row's own currency when the sheet says otherwise): amounts in
different currencies are grouped, never added (no FX in this round).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change_cost import LABOUR_KINDS, CostingPosition, DepartmentRate
from app.models.cost_sheet import CostSheetMachineClass, CostSheetVersion
from app.models.entities import Plant, Project
from app.core.display import fmt_number
from app.services import cost_sheet_service as cs
from app.utils.clock import business_today

NO_RATE = "No rate in the cost sheet"
def unpriced_department_messages(unpriced: list[dict],
                                 names: dict) -> list[tuple[str, int]]:
    """One "No cost sheet rate for <department>: hours unpriced" per
    department with an unpriced line (department order of first
    appearance), as (message, department_id). The same words in the
    costing, the close-costing dialog and the P&L."""
    seen: list[int] = []
    for u in unpriced:
        if u["department_id"] not in seen:
            seen.append(u["department_id"])
    return [(f"No cost sheet rate for "
             f"{names.get(d) or f'department {d}'}: hours unpriced", d) for d in seen]


async def unpriced_departments(db: AsyncSession, change) -> list[dict]:
    """[{department_id, department_name, count, message}] for the costing
    positions of `change` that cannot be priced from the cost sheet (no
    rate: never counted as 0). Read-only; what the close-costing dialog and
    the P&L card name."""
    from app.models.change_cost import CostingPosition
    from app.models.workflow import Department
    positions = (await db.execute(select(CostingPosition).where(
        CostingPosition.change_id == change.id))).scalars().all()
    if not positions:
        return []
    plant_id = await costing_plant_id(db, change)
    org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    book = RateBook(db)
    unpriced: list[dict] = []
    for p in positions:
        price = await position_price(db, change, p, org_id=org_id,
                                     plant_id=plant_id, book=book)
        if line_value(p, price) is None:
            unpriced.append({"department_id": p.department_id, "position_id": p.id})
    if not unpriced:
        return []
    names = dict((await db.execute(select(Department.id, Department.name).where(
        Department.id.in_({u["department_id"] for u in unpriced})))).all())
    counts: dict[int, int] = {}
    for u in unpriced:
        counts[u["department_id"]] = counts.get(u["department_id"], 0) + 1
    return [{"department_id": d, "department_name": names.get(d),
             "count": counts[d], "message": m}
            for m, d in unpriced_department_messages(unpriced, names)]


NO_RATE_WARNING = ("Costing lines without a rate in the cost sheet are not counted: "
                   "the cost is too low")


@dataclass
class Price:
    """One looked-up rate and where it came from."""
    rate: Optional[float]
    currency: str
    source: Optional[str]            # cost_sheet | department_rate | None
    unit: str = "h"                  # h | trial
    version_id: Optional[int] = None
    version: Optional[int] = None
    match: Optional[str] = None
    detail: dict = field(default_factory=dict)

    @property
    def missing(self) -> bool:
        return self.rate is None


def fmt_amount(value: float) -> str:
    """21.5 -> '21.50', 1250 -> '1,250.00' (the UI's en-US number format)."""
    return fmt_number(value, 2)


def rate_label(price: Optional[Price], *, department: Optional[str] = None,
               position: Optional[str] = None, machine_class: Optional[str] = None) -> str:
    """'Cost sheet v2, Tool Engineer, Engineer, 21.50 USD/h'."""
    if price is None or price.rate is None:
        return NO_RATE
    head = (f"Cost sheet v{price.version}" if price.source == "cost_sheet"
            else "Department rate")
    parts = [head]
    if machine_class:
        parts.append(("Sampling " if price.unit == "trial" else "Machine ") + machine_class)
    else:
        if department:
            parts.append(department)
        if position:
            parts.append(position)
    parts.append(f"{fmt_amount(price.rate)} {price.currency}/{price.unit}")
    return ", ".join(parts)


# ---------------------------------------------------------------- context

async def costing_plant_id(db: AsyncSession, change) -> Optional[int]:
    """The plant a change is costed at: its own affected plant when it names
    exactly one, else its project's (the summation's and the P&L's rule).
    Asked in SQL: summations run on hand-built changes whose relationships
    were never loaded."""
    from app.models.change import change_affected_plants
    plants = (await db.execute(
        select(change_affected_plants.c.plant_id).where(
            change_affected_plants.c.change_id == change.id))).scalars().all()
    if len(plants) == 1:
        return plants[0]
    if change.project_id is None:
        return None
    return (await db.execute(select(Project.plant_id).where(
        Project.id == change.project_id))).scalar_one_or_none()


async def org_id_of_plant(db: AsyncSession, plant_id: Optional[int]) -> Optional[int]:
    if plant_id is None:
        return None
    return (await db.execute(select(Plant.organization_id).where(
        Plant.id == plant_id))).scalar_one_or_none()


async def change_org_id(db: AsyncSession, change) -> Optional[int]:
    if change.project_id is None:
        return None
    return (await db.execute(
        select(Plant.organization_id).join(Project, Project.plant_id == Plant.id)
        .where(Project.id == change.project_id))).scalar_one_or_none()


class RateBook:
    """Request-scoped rate lookups: each organisation's published cost sheet
    versions are loaded once (rates, overheads, machine and sampling rows ride
    along by selectin) and the version valid on a date is picked in Python;
    plant currencies and the legacy department_rate table are read once too.
    A list that prices many lines on many dates (the P&L portfolio) then costs
    a fixed number of queries instead of one lookup per line and date."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._versions: dict[int, list[CostSheetVersion]] = {}
        self._plant_cur: Optional[dict[int, str]] = None
        self._legacy: Optional[dict[tuple[int, int], tuple]] = None
        self._classes: dict[int, list] = {}

    async def versions(self, org_id: Optional[int]) -> list[CostSheetVersion]:
        if org_id is None:
            return []
        if org_id not in self._versions:
            self._versions[org_id] = list((await self.db.execute(
                select(CostSheetVersion).where(
                    CostSheetVersion.organization_id == org_id,
                    CostSheetVersion.status == "published"))).scalars().all())
        return self._versions[org_id]

    async def has_cost_sheet(self, org_id: Optional[int]) -> bool:
        return bool(await self.versions(org_id))

    async def class_for_tonnage(self, org_id: Optional[int],
                                tonnage: Optional[float]) -> Optional[int]:
        """The org's machine class whose band holds the tonnage."""
        if org_id is None or tonnage is None:
            return None
        if org_id not in self._classes:
            self._classes[org_id] = await cs.list_machine_classes(self.db, org_id)
        classes = self._classes[org_id]
        name = cs.class_for_tonnage(classes, float(tonnage))
        return next((c.id for c in classes if c.name == name), None)

    async def version_on(self, org_id: Optional[int],
                         on_date: Optional[date] = None) -> Optional[CostSheetVersion]:
        """cost_sheet_service.version_on, from the loaded versions."""
        on_date = on_date or business_today()
        valid = [v for v in await self.versions(org_id)
                 if v.valid_from is not None and v.valid_from <= on_date]
        return max(valid, key=lambda v: (v.valid_from, v.version), default=None)

    async def plant_currency(self, plant_id: Optional[int]) -> str:
        if plant_id is None:
            return "EUR"
        if self._plant_cur is None:
            self._plant_cur = {pid: cur for pid, cur in (await self.db.execute(
                select(Plant.id, Plant.currency))).all()}
        return self._plant_cur.get(plant_id) or "EUR"

    async def legacy_rate(self, department_id: int,
                          plant_id: Optional[int]) -> Optional[float]:
        if plant_id is None:
            return None
        if self._legacy is None:
            self._legacy = {}
            for r in (await self.db.execute(select(DepartmentRate))).scalars().all():
                key = (r.department_id, r.plant_id)
                rank = (r.effective_from or date.min, r.id)
                if key not in self._legacy or rank > self._legacy[key][0]:
                    self._legacy[key] = (rank, r.hourly_rate)
        hit = self._legacy.get((department_id, plant_id))
        return hit[1] if hit else None

    async def _no_hit(self, org_id, plant_id, on_date, unit, reason) -> Price:
        v = await self.version_on(org_id, on_date)
        return Price(rate=None, currency=await self.plant_currency(plant_id),
                     source="cost_sheet", unit=unit,
                     version_id=v.id if v else None, version=v.version if v else None,
                     detail={"missing": [reason]})

    async def labour_price(self, org_id: Optional[int], department_id: int,
                           plant_id: Optional[int], position: Optional[str] = None,
                           on_date: Optional[date] = None) -> Price:
        """The effective labour rate (base + personnel overhead) of the
        version valid on on_date; department_rate only for an org without a
        cost sheet."""
        on_date = on_date or business_today()
        if await self.has_cost_sheet(org_id):
            v = await self.version_on(org_id, on_date)
            hit = (cs.rate_in_version(v, department_id, position, plant_id,
                                      with_overhead=True) if v else None)
            if hit is None:
                return await self._no_hit(org_id, plant_id, on_date, "h", "labour_rate")
            return _from_hit(hit)
        rate = await self.legacy_rate(department_id, plant_id)
        return Price(rate=rate, currency=await self.plant_currency(plant_id),
                     source="department_rate" if rate is not None else None,
                     detail={} if rate is not None else {"missing": ["labour_rate"]})

    async def machine_price(self, org_id: Optional[int], machine_class_id: Optional[int],
                            plant_id: Optional[int], on_date: Optional[date] = None) -> Price:
        on_date = on_date or business_today()
        if machine_class_id is None:
            return Price(rate=None, currency=await self.plant_currency(plant_id),
                         source=None, detail={"missing": ["machine_class"]})
        v = await self.version_on(org_id, on_date)
        hit = cs.machine_rate_in_version(v, machine_class_id, plant_id) if v else None
        if hit is None:
            return await self._no_hit(org_id, plant_id, on_date, "h", "machine_rate")
        return _from_hit(hit)

    async def sampling_price(self, org_id: Optional[int], machine_class_id: Optional[int],
                             plant_id: Optional[int], on_date: Optional[date] = None) -> Price:
        on_date = on_date or business_today()
        if machine_class_id is None:
            return Price(rate=None, currency=await self.plant_currency(plant_id),
                         source=None, unit="trial", detail={"missing": ["machine_class"]})
        v = await self.version_on(org_id, on_date)
        hit = cs.sampling_in_version(v, machine_class_id, plant_id) if v else None
        if hit is None:
            return await self._no_hit(org_id, plant_id, on_date, "trial", "sampling_rate")
        return _from_hit(hit, unit="trial")


async def has_cost_sheet(db: AsyncSession, org_id: Optional[int],
                         book: Optional[RateBook] = None) -> bool:
    """True once the org has any published version: from then on the old
    department_rate table is never read again for it."""
    return await (book or RateBook(db)).has_cost_sheet(org_id)


def _from_hit(hit, unit: str = "h") -> Price:
    return Price(rate=hit.rate, currency=hit.currency, source="cost_sheet", unit=unit,
                 version_id=hit.version_id, version=hit.version, match=hit.match,
                 detail=({"missing": hit.breakdown.get("missing")}
                         if hit.breakdown.get("missing") else {}))


async def labour_price(db: AsyncSession, org_id: Optional[int], department_id: int,
                       plant_id: Optional[int], position: Optional[str] = None,
                       on_date: Optional[date] = None, *,
                       book: Optional[RateBook] = None) -> Price:
    return await (book or RateBook(db)).labour_price(
        org_id, department_id, plant_id, position, on_date)


async def machine_price(db: AsyncSession, org_id: Optional[int],
                        machine_class_id: Optional[int], plant_id: Optional[int],
                        on_date: Optional[date] = None, *,
                        book: Optional[RateBook] = None) -> Price:
    return await (book or RateBook(db)).machine_price(
        org_id, machine_class_id, plant_id, on_date)


async def sampling_price(db: AsyncSession, org_id: Optional[int],
                         machine_class_id: Optional[int], plant_id: Optional[int],
                         on_date: Optional[date] = None, *,
                         book: Optional[RateBook] = None) -> Price:
    return await (book or RateBook(db)).sampling_price(
        org_id, machine_class_id, plant_id, on_date)


# ---------------------------------------------------------------- machine class

async def impacted_tonnage(db: AsyncSession, change) -> Optional[float]:
    """The largest tool_tonnage_class among the change's impacted items."""
    from app.models.change import ChangeImpactedItem
    from app.models.part import Part
    rows = (await db.execute(
        select(Part.tool_tonnage_class).join(
            ChangeImpactedItem, ChangeImpactedItem.part_id == Part.id)
        .where(ChangeImpactedItem.change_id == change.id,
               Part.tool_tonnage_class.is_not(None)))).scalars().all()
    return float(max(rows)) if rows else None


async def default_machine_class(db: AsyncSession, org_id: Optional[int], change
                                ) -> tuple[Optional[CostSheetMachineClass], Optional[float]]:
    """(class, tonnage): the class whose band holds the impacted tool's
    tonnage, when the tonnage is known."""
    tonnage = await impacted_tonnage(db, change)
    if tonnage is None or org_id is None:
        return None, tonnage
    classes = await cs.list_machine_classes(db, org_id)
    name = cs.class_for_tonnage(classes, tonnage)
    return next((c for c in classes if c.name == name), None), tonnage


async def change_machine_class_id(db: AsyncSession, change,
                                  org_id: Optional[int] = None) -> Optional[int]:
    """The change's own class, else the tonnage default."""
    if getattr(change, "machine_class_id", None):
        return change.machine_class_id
    if org_id is None:
        org_id = await change_org_id(db, change)
    c, _ = await default_machine_class(db, org_id, change)
    return c.id if c is not None else None


# ---------------------------------------------------------------- lines

def quantity(p: CostingPosition) -> float:
    """What the line's rate multiplies: trials for sampling, hours else."""
    if p.kind == "sampling":
        return float(p.trials or 0)
    return float(p.hours or 0)


async def price_for_position(db: AsyncSession, change, p: CostingPosition, *,
                             org_id: Optional[int] = None, plant_id: Optional[int] = None,
                             on_date: Optional[date] = None,
                             book: Optional[RateBook] = None) -> Price:
    """The line's price now. A machine_time / sampling line without its own
    class is priced on the change's class (own or tonnage default); the class
    used is recorded in detail["machine_class_id"]."""
    book = book or RateBook(db)
    if plant_id is None:
        plant_id = await costing_plant_id(db, change)
    if org_id is None:
        org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    if p.kind in ("machine_time", "sampling"):
        cls_id = p.machine_class_id or await change_machine_class_id(db, change, org_id)
        fn = book.machine_price if p.kind == "machine_time" else book.sampling_price
        price = await fn(org_id, cls_id, plant_id, on_date)
        if cls_id is not None:
            price.detail = {**price.detail, "machine_class_id": cls_id}
        return price
    return await book.labour_price(org_id, p.department_id, plant_id,
                                   p.labour_position, on_date)


async def snapshot_position(db: AsyncSession, change, p: CostingPosition,
                            on_date: Optional[date] = None) -> Price:
    """Price the line now and store the snapshot on it (rate, rate currency,
    version). Called when a line is created or its pricing inputs change.

    A line with a class of its own keeps it; a line priced on the change's
    class keeps machine_class_id None (so a later change of the class moves
    it) and records the class used in rate_detail. A line that found no rate
    stores no snapshot (rate_on None): it is priced live until a rate exists.
    The money currency (p.currency, of est_cost and offers) is the costing
    plant's and is not the rate's business."""
    on_date = on_date or business_today()
    price = await price_for_position(db, change, p, on_date=on_date)
    p.rate = price.rate
    p.rate_currency = price.currency
    if p.currency is None:
        p.currency = await costing_currency(db, change)
    p.rate_source = price.source
    p.cost_sheet_version_id = price.version_id
    p.cost_sheet_version = price.version
    p.rate_match = price.match
    p.rate_on = on_date if price.rate is not None else None
    p.rate_detail = {"unit": price.unit, **price.detail} or None
    return price


def stored_price(p: CostingPosition) -> Optional[Price]:
    """The snapshot on the line; None for a line not priced yet (before 098,
    or no rate found when it was costed)."""
    if p.rate_on is None or p.rate is None:
        return None
    detail = dict(p.rate_detail or {})
    unit = detail.pop("unit", "trial" if p.kind == "sampling" else "h")
    return Price(rate=p.rate, currency=p.rate_currency or p.currency or "EUR",
                 source=p.rate_source, unit=unit, version_id=p.cost_sheet_version_id,
                 version=p.cost_sheet_version, match=p.rate_match, detail=detail)


async def position_price(db: AsyncSession, change, p: CostingPosition, *,
                         org_id=None, plant_id=None,
                         book: Optional[RateBook] = None) -> Price:
    """The snapshot, or for a line without one, the rate valid today (read
    only: GETs never write)."""
    return stored_price(p) or await price_for_position(
        db, change, p, org_id=org_id, plant_id=plant_id, book=book)


def line_value(p: CostingPosition, price: Price) -> Optional[float]:
    """hours x rate / trials x price; None = cannot price (never 0); 0.0
    when there is nothing to price."""
    q = quantity(p)
    if not q:
        return 0.0
    if price.rate is None:
        return None
    return round(q * price.rate, 2)


async def class_names(db: AsyncSession, org_id: Optional[int]) -> dict[int, str]:
    if org_id is None:
        return {}
    return {c.id: c.name for c in await cs.list_machine_classes(
        db, org_id, include_inactive=True)}


async def describe_positions(db: AsyncSession, change, positions) -> dict[int, dict]:
    """{position id: pricing fields} for the costing table: rate, currency,
    unit, source, version, label, line value, missing."""
    if not positions:
        return {}
    from app.models.workflow import Department
    plant_id = await costing_plant_id(db, change)
    org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    names = dict((await db.execute(select(Department.id, Department.name))).all())
    classes = await class_names(db, org_id)
    book = RateBook(db)
    money_currency = await book.plant_currency(plant_id)
    out = {}
    for p in positions:
        price = await position_price(db, change, p, org_id=org_id, plant_id=plant_id,
                                     book=book)
        value = line_value(p, price)
        # the line's own class, else the change's class it was priced on
        used_cls = p.machine_class_id or price.detail.get("machine_class_id")
        cls = classes.get(used_cls) if used_cls else None
        out[p.id] = {
            "rate": price.rate, "rate_currency": price.currency,
            "currency": p.currency or money_currency,
            "machine_class_used_id": used_cls,
            "machine_class_from_change": bool(
                p.kind in ("machine_time", "sampling") and used_cls
                and not p.machine_class_id),
            "rate_unit": price.unit, "rate_source": price.source,
            "cost_sheet_version_id": price.version_id,
            "cost_sheet_version": price.version,
            "rate_match": price.match, "rate_on": p.rate_on,
            "rate_label": rate_label(
                price, department=names.get(p.department_id),
                position=p.labour_position,
                machine_class=cls if p.kind in ("machine_time", "sampling") else None),
            "rate_missing": price.rate is None and quantity(p) > 0,
            "rate_missing_reason": (price.detail.get("missing") or [None])[0]
            if price.rate is None else None,
            "rate_is_snapshot": p.rate_on is not None,
            "line_value": value,
            "machine_class": cls,
        }
    return out


PRICING_FIELDS = ("kind", "hours", "labour_position", "machine_class_id", "trials")


def is_labour(kind: str) -> bool:
    return kind in LABOUR_KINDS


# ---------------------------------------------------------------- context API

async def costing_context(db: AsyncSession, change) -> dict:
    """What the costing table needs besides the lines: the costing plant and
    its currency, the cost sheet version in force today and whether Finance
    owes a review, the machine classes with the change's class (own or the
    tonnage default), and the positions each department has a rate for."""
    plant_id = await costing_plant_id(db, change)
    org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    plant = await db.get(Plant, plant_id) if plant_id is not None else None
    sheet = await has_cost_sheet(db, org_id)
    current = await cs.version_on(db, org_id) if org_id is not None else None
    latest = await cs.latest_published(db, org_id) if org_id is not None else None
    classes = await cs.list_machine_classes(db, org_id) if org_id is not None else []
    default_cls, tonnage = await default_machine_class(db, org_id, change)
    effective = change.machine_class_id or (default_cls.id if default_cls else None)
    positions: dict[int, list[str]] = {}
    if current is not None:
        for r in current.rates:
            if r.position and (r.plant_id is None or r.plant_id == plant_id):
                names = positions.setdefault(r.department_id, [])
                if r.position not in names:
                    names.append(r.position)
    stale = await cs.stale_status(db, org_id) if (org_id is not None and sheet) else None
    return {
        "plant_id": plant_id,
        "plant_name": plant.name if plant else None,
        "currency": await cs.plant_currency(db, plant_id),
        "rate_source": "cost_sheet" if sheet else "department_rate",
        "current_version": ({"id": current.id, "version": current.version,
                             "valid_from": current.valid_from} if current else None),
        "latest_version": latest.version if latest else None,
        "stale": stale,
        "machine_classes": [{"id": c.id, "name": c.name, "tonnage_min": c.tonnage_min,
                             "tonnage_max": c.tonnage_max} for c in classes],
        "machine_class_id": change.machine_class_id,
        "default_machine_class_id": default_cls.id if default_cls else None,
        "effective_machine_class_id": effective,
        "tonnage": tonnage,
        "positions_by_department": {str(k): sorted(v) for k, v in positions.items()},
    }


class MachineClassLocked(ValueError):
    """The change is past costing: its machine class is frozen (HTTP 409)."""


def machine_class_open(change, user) -> bool:
    """The class moves prices, so it changes only while the change is in
    costing; admins are exempt (a correction after the fact is audited)."""
    return change.status == "costing" or user.effective_role == "admin"


async def may_set_machine_class(db: AsyncSession, change, user) -> bool:
    """Admins always; PM and a routed department's member (while it may
    write its own costing) only while the change is in costing."""
    from app.models.change import ChangeAssessment
    from app.services.costing_position_service import CostingPositionService
    from app.services.meeting_service import MeetingService
    from app.services.workflow_service import WorkflowService
    if user.effective_role == "admin":
        return True
    if change.status != "costing":
        return False
    if await MeetingService.user_is_pm_member(db, user):
        return True
    mine = set(await WorkflowService.effective_department_ids(db, user))
    routed = set((await db.execute(select(ChangeAssessment.department_id).where(
        ChangeAssessment.change_id == change.id))).scalars().all())
    for dept in mine & routed:
        if await CostingPositionService.may_write(db, change, dept, user):
            return True
    return False


async def set_machine_class(db: AsyncSession, change, machine_class_id: Optional[int],
                            user) -> None:
    """Set (None: back to the tonnage default) the change's class and
    re-price every machine_time / sampling line that has no class of its
    own: they were priced on the change's class. Audited, with the lines
    re-priced."""
    if not machine_class_open(change, user):
        raise MachineClassLocked(
            "The machine class can only be changed while the change is in costing")
    org_id = await change_org_id(db, change)
    names = await class_names(db, org_id)
    if machine_class_id is not None and machine_class_id not in names:
        raise ValueError(f"Unknown machine class {machine_class_id}")
    old = change.machine_class_id
    if old == machine_class_id:
        return
    old_effective = await change_machine_class_id(db, change, org_id)
    change.machine_class_id = machine_class_id
    await db.flush()
    new_effective = await change_machine_class_id(db, change, org_id)
    repriced = []
    if new_effective != old_effective:
        lines = (await db.execute(select(CostingPosition).where(
            CostingPosition.change_id == change.id,
            CostingPosition.kind.in_(("machine_time", "sampling")),
            CostingPosition.machine_class_id.is_(None)))).scalars().all()
        for p in lines:
            before = (p.rate, p.cost_sheet_version)
            await snapshot_position(db, change, p)
            repriced.append({"position_id": p.id, "label": p.label,
                             "old_rate": before[0], "new_rate": p.rate})
        await db.flush()
    from app.services.change_service import ChangeService
    await ChangeService.append_changelog(
        db, change, "machine_class_set",
        f"Machine class set to {names.get(machine_class_id, 'the tonnage default')}"
        + (f"; {len(repriced)} line(s) re-priced" if repriced else ""),
        user.id, field_name="machine_class_id",
        old_value=names.get(old) if old else None,
        new_value={"machine_class": names.get(machine_class_id) if machine_class_id
                   else None, "repriced": repriced})


# ---------------------------------------------------------------- actuals

async def price_bookings(db: AsyncSession, change, bookings, *,
                         org_id: Optional[int] = None,
                         plant_id: Optional[int] = None,
                         book: Optional[RateBook] = None) -> list[dict]:
    """Each implementation booking priced on its booking date: hours x the
    effective labour rate (department, the booking's position if it names
    one, the costing plant) valid that day, plus machine hours x the machine
    class rate valid that day. A value None = cannot price (never 0)."""
    if plant_id is None:
        plant_id = await costing_plant_id(db, change)
    if org_id is None:
        org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    book = book or RateBook(db)
    labour: dict[tuple, Price] = {}
    machine: dict[tuple, Price] = {}
    out = []
    for b in bookings:
        on = (b.booked_at.date() if b.booked_at else business_today())
        key = (b.department_id, getattr(b, "labour_position", None), on)
        if key not in labour:
            labour[key] = await book.labour_price(org_id, b.department_id, plant_id,
                                                  key[1], on)
        lp = labour[key]
        hours = float(b.hours or 0.0)
        mh = float(getattr(b, "machine_hours", None) or 0.0)
        mp = None
        if mh:
            mkey = (getattr(b, "machine_class_id", None), on)
            if mkey not in machine:
                machine[mkey] = await book.machine_price(org_id, mkey[0], plant_id, on)
            mp = machine[mkey]
        out.append({
            "booking_id": b.id, "department_id": b.department_id, "on": on,
            "hours": hours, "labour_rate": lp.rate, "labour_currency": lp.currency,
            "labour_version": lp.version,
            "labour_value": (round(hours * lp.rate, 2) if lp.rate is not None
                             else (0.0 if not hours else None)),
            "machine_hours": mh,
            "machine_rate": mp.rate if mp else None,
            "machine_currency": mp.currency if mp else None,
            "machine_value": ((round(mh * mp.rate, 2) if mp.rate is not None else None)
                              if mp else 0.0),
        })
    return out


# ---------------------------------------------------------------- warnings

async def costing_versions(db: AsyncSession, change) -> list[int]:
    """The cost sheet version numbers the change's costing lines were
    priced with (position snapshots and cost lines)."""
    from app.models.change import ChangeAssessment
    from app.models.change_cost import AssessmentCostLine
    nums = set((await db.execute(select(CostingPosition.cost_sheet_version).where(
        CostingPosition.change_id == change.id,
        CostingPosition.cost_sheet_version.is_not(None)))).scalars().all())
    ids = set((await db.execute(
        select(AssessmentCostLine.cost_sheet_version_id)
        .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
        .where(ChangeAssessment.change_id == change.id,
               AssessmentCostLine.cost_sheet_version_id.is_not(None)))).scalars().all())
    if ids:
        nums |= set((await db.execute(select(CostSheetVersion.version).where(
            CostSheetVersion.id.in_(ids)))).scalars().all())
    return sorted(nums)


async def version_warning(db: AsyncSession, change, used: Optional[list[int]] = None
                          ) -> Optional[str]:
    """'Costing used cost sheet v1, current is v2' when a costing line was
    priced with another version than the one valid today."""
    org_id = await change_org_id(db, change)
    if org_id is None:
        return None
    current = await cs.version_on(db, org_id)
    if current is None:
        return None
    used = used if used is not None else await costing_versions(db, change)
    old = [v for v in used if v != current.version]
    if not old:
        return None
    return (f"Costing used cost sheet {', '.join(f'v{v}' for v in old)}, "
            f"current is v{current.version}")


async def costing_currency(db: AsyncSession, change) -> str:
    return await cs.plant_currency(db, await costing_plant_id(db, change))


async def costing_currency_or_none(db: AsyncSession, change) -> Optional[str]:
    """The costing plant's currency, or None when the change has no costing
    plant (no single affected plant and no project plant): the caller shows
    the amount unitless instead of assuming EUR."""
    plant_id = await costing_plant_id(db, change)
    if plant_id is None:
        return None
    return await cs.plant_currency(db, plant_id)
