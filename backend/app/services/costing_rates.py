"""Costing priced from the Finance cost sheet (spec §15 phase 2).

One place that answers "what is an hour (a machine hour, a trial) of this
worth on this change, and where does the number come from":

- labour hours: `cost_sheet_service.effective_labour_rate` (department +
  the costing plant; one rate per department per plant since 104), with the
  version valid on the change's creation date (change_pricing_date);
- machine_time lines: the machine class rate; sampling lines: the price of
  one trial of the class. A line that names a MachineDB machine (105) is
  priced on that machine's own rate when the version has one, else on the
  class rate at the machine's plant;
- the legacy `department_rate` table only when the organisation has no
  published cost sheet version at all.

A change older than the first published version is priced with that first
version ("priced with v1, the earliest cost sheet"). Where the version
valid on the creation date has no rate (no row, or an empty one) for the
department, machine class or sampling at the plant, the earliest LATER
published version with one prices it, labelled ("no rate in v1 on the
creation date; taken from v2 valid from ..."); a rate that existed then is
never replaced by a later one. The snapshot records the version used.

A Price with rate None means "cannot price": the line shows "No rate in the
cost sheet" and is never counted as 0. The currency is the costing plant's
(the rate row's own currency when the sheet says otherwise): amounts in
different currencies are grouped, never added (no FX in this round).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change_cost import LABOUR_KINDS, CostingPosition, DepartmentRate
from app.models.cost_sheet import CostSheetMachineClass, CostSheetVersion
from app.models.entities import Plant, Project
from app.core.display import fmt_date, fmt_number
from app.services import cost_sheet_service as cs
from app.services import cost_sheet_machines_service as msvc
from app.utils.clock import business_date_of, business_today

NO_RATE = "No rate in the cost sheet"

# ---------------------------------------------------------------- pricing date
#
# A change is priced with the cost sheet version valid on the day it was
# CREATED (change_requests.created_at, as a business date), never the day a
# line was entered: a later rate update never moves an existing change. Lines
# keep their snapshot; a line without one is priced on the creation date.
#
# Booked actual hours (the P&L's actuals) are priced on the booking date for
# now. BOOKING_PRICING_BASIS switches them to the change's creation date
# ("change_created") in one place: booking_pricing_date.
BOOKING_PRICING_BASIS = "booking_date"      # "booking_date" | "change_created"


def change_pricing_date(change) -> date:
    """The day whose cost sheet version prices this change: its creation
    date in the business timezone (today for a change not saved yet)."""
    return business_date_of(getattr(change, "created_at", None)) or business_today()


def booking_pricing_date(change, booked_at) -> date:
    """The day whose version prices a booking (or a booking made now, when
    booked_at is None): the booking date, or the change's creation date when
    BOOKING_PRICING_BASIS says so."""
    if BOOKING_PRICING_BASIS == "change_created":
        return change_pricing_date(change)
    return booked_at.date() if booked_at else business_today()

def _qty(n: float) -> str:
    """12 -> '12', 1250.5 -> '1,250.5' (the UI's formatNumber, up to 2 decimals)."""
    return f"{n:,.2f}".rstrip("0").rstrip(".")


def unpriced_groups(unpriced: list[dict], names: dict) -> list[dict]:
    """The unpriced lines said once per what is missing, in order of first
    appearance: a labour line per department ("No cost sheet rate for Tool
    Engineer: 12 h unpriced"), a machine_time or sampling line per class and
    plant (its `subject`: "No machine rate for class 200-450 t at USA
    Toccoa: 12 h unpriced"). The quantities are said when the lines carry
    them (quantity, unit), else "hours". [{message, department_id, subject,
    count}]; department_id is None for a subject group (it is not the
    department's rate that is missing)."""
    groups: dict = {}
    for u in unpriced:
        subject = u.get("subject")
        key = ("subject", subject) if subject else ("department", u["department_id"])
        g = groups.setdefault(key, {"subject": subject, "department_id": u["department_id"],
                                    "hours": 0.0, "trials": 0.0, "count": 0})
        g["count"] += 1
        q = float(u.get("quantity") or 0)
        if u.get("unit") == "trial":
            g["trials"] += q
        else:
            g["hours"] += q
    out = []
    for g in groups.values():
        parts = ([f"{_qty(g['hours'])} h"] if g["hours"] > 0 else []) + (
            [f"{_qty(g['trials'])} trial{'' if g['trials'] == 1 else 's'}"]
            if g["trials"] > 0 else [])
        what = " and ".join(parts) or "hours"
        if g["subject"]:
            message = f"No {g['subject']}: {what} unpriced"
        else:
            d = g["department_id"]
            message = (f"No cost sheet rate for {names.get(d) or f'department {d}'}: "
                       f"{what} unpriced")
        out.append({"message": message, "subject": g["subject"], "count": g["count"],
                    "department_id": None if g["subject"] else g["department_id"]})
    return out


def unpriced_department_messages(unpriced: list[dict],
                                 names: dict) -> list[tuple[str, Optional[int]]]:
    """unpriced_groups as (message, department_id): the same words in the
    costing, the close-costing dialog and the P&L."""
    return [(g["message"], g["department_id"]) for g in unpriced_groups(unpriced, names)]


async def unpriced_subject(book: "RateBook", p, price: "Price", plant_id: Optional[int],
                           classes: dict) -> Optional[str]:
    """What is missing for an unpriced machine_time or sampling line: the
    machine (sampling) rate of its class at the plant it is priced at, or
    the machine class itself. None for a labour line (the department's rate
    is missing)."""
    if p.kind not in ("machine_time", "sampling"):
        return None
    cls_id = p.machine_class_id or (price.detail or {}).get("machine_class_id")
    if cls_id is None:
        return "machine class for " + ("sampling" if p.kind == "sampling"
                                       else "the machine hours")
    m = await book.machine(getattr(p, "machine_id", None))
    at = (m.plant_id if m is not None and m.plant_id else None) or plant_id
    plant = await book.plant_name(at)
    what = "sampling rate" if p.kind == "sampling" else "machine rate"
    return (f"{what} for class {classes.get(cls_id) or f'#{cls_id}'}"
            + (f" at {plant}" if plant else ""))


async def unpriced_departments(db: AsyncSession, change) -> list[dict]:
    """[{department_id, department_name, subject, count, message}] for the
    costing positions of `change` that cannot be priced from the cost sheet
    (no rate: never counted as 0), one per unpriced_groups group.
    Read-only; what the close-costing dialog and the P&L card name."""
    from app.models.change_cost import CostingPosition
    from app.models.workflow import Department
    positions = (await db.execute(select(CostingPosition).where(
        CostingPosition.change_id == change.id))).scalars().all()
    if not positions:
        return []
    plant_id = await costing_plant_id(db, change)
    org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    book = RateBook(db)
    classes: Optional[dict] = None
    unpriced: list[dict] = []
    for p in positions:
        price = await position_price(db, change, p, org_id=org_id,
                                     plant_id=plant_id, book=book)
        if line_value(p, price) is None:
            if classes is None and p.kind in ("machine_time", "sampling"):
                classes = await class_names(db, org_id)
            unpriced.append({"department_id": p.department_id, "position_id": p.id,
                             "quantity": quantity(p), "unit": price.unit,
                             "subject": await unpriced_subject(book, p, price, plant_id,
                                                               classes or {})})
    if not unpriced:
        return []
    names = dict((await db.execute(select(Department.id, Department.name).where(
        Department.id.in_({u["department_id"] for u in unpriced})))).all())
    return [{"department_id": g["department_id"],
             "department_name": names.get(g["department_id"]),
             "subject": g["subject"], "count": g["count"], "message": g["message"]}
            for g in unpriced_groups(unpriced, names)]


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
    """'Cost sheet v2, Tool Engineer, 21.50 USD/h'. position is kept for
    callers but no longer shown: rates are per department (104)."""
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
    parts.append(f"{fmt_amount(price.rate)} {price.currency}/{price.unit}")
    fx = (price.detail or {}).get("fx")
    if fx:
        # a machine rate in another currency, converted at the version's rate
        parts.append(f"converted from {fmt_amount(fx['from_rate'])} {fx['from_currency']} "
                     f"at {fx_direction(fx['rate'], price.currency, fx['from_currency'])}")
    note = pricing_note(price)
    if note:
        parts.append(note)
    return ", ".join(parts)


def pricing_note(price: Optional[Price]) -> Optional[str]:
    """Why the price does not come from the version valid on the change's
    creation date, or None: 'priced with v1, the earliest cost sheet' (the
    change is older than the first version), or 'no rate in v1 on the
    creation date; taken from v2 valid from 26 Sep 2026' (gap fill)."""
    detail = (price.detail or {}) if price is not None else {}
    gap = detail.get("gap_fill")
    if gap:
        where = (", the earliest cost sheet" if detail.get("earliest")
                 else " on the creation date")
        if gap.get("part") == "labour_rate":
            # a sampling row of the version whose labour rate alone was missing
            return (f"no labour rate in v{gap['no_rate_in']}{where}; labour rate taken "
                    f"from v{gap['version']} valid from {fmt_date(gap.get('valid_from'))}")
        return (f"no rate in v{gap['no_rate_in']}{where}; taken from v{gap['version']} "
                f"valid from {fmt_date(gap.get('valid_from'))}")
    if detail.get("earliest") and price.version is not None:
        return f"priced with v{price.version}, the earliest cost sheet"
    return None


def fx_direction(rate, base: str, quote: str) -> str:
    """'1 USD = 17.30 MXN' for `rate` units of quote per one base, written
    the way round that reads above 1 (an inverted pair is turned back)."""
    try:
        r = Decimal(str(rate))
    except Exception:
        return f"{rate} {quote}/{base}"
    if 0 < r < 1:
        return f"1 {quote} = {fmt_fx(Decimal(1) / r)} {base}"
    return f"1 {base} = {fmt_fx(r)} {quote}"


def fmt_fx(rate) -> str:
    """An exchange rate as text: 2 decimals when that is exact (17.30),
    else 4 (an inverted pair: 1/17.30 = 0.0578)."""
    try:
        r = float(rate)
    except (TypeError, ValueError):
        return str(rate)
    return fmt_number(r, 2) if round(r, 2) == round(r, 6) else fmt_number(r, 4)


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
        self._machines: dict[int, object] = {}

    async def machine(self, machine_id: Optional[int]):
        """The synced MachineDB machine (cost_sheet_machines row), cached."""
        if machine_id is None:
            return None
        if machine_id not in self._machines:
            from app.models.cost_sheet_machines import CostSheetMachine
            self._machines[machine_id] = await self.db.get(CostSheetMachine, machine_id)
        return self._machines[machine_id]

    async def machine_class_of(self, org_id: Optional[int],
                               machine_id: Optional[int]) -> Optional[int]:
        """The cost sheet class the named machine's tonnage falls in."""
        m = await self.machine(machine_id)
        if m is None or m.clamping_force_t is None:
            return None
        return await self.class_for_tonnage(org_id, float(m.clamping_force_t))

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

    async def chain(self, org_id: Optional[int]) -> list[CostSheetVersion]:
        """The published versions in validity order (valid_from, version)."""
        return sorted((v for v in await self.versions(org_id) if v.valid_from is not None),
                      key=lambda v: (v.valid_from, v.version))

    async def pricing_version(self, org_id: Optional[int], on_date: Optional[date] = None
                              ) -> tuple[Optional[CostSheetVersion], bool]:
        """(version, earliest): the version valid on on_date; a date before
        the first published version is priced with that first version
        (earliest True, and the label says so)."""
        v = await self.version_on(org_id, on_date)
        if v is not None:
            return v, False
        chain = await self.chain(org_id)
        return (chain[0], True) if chain else (None, False)

    async def gap_fill(self, org_id: Optional[int], v: CostSheetVersion, lookup,
                       usable=lambda found: found is not None):
        """(found, later version) from the earliest LATER published version
        where lookup(version) is usable, else None. Only for a rate that the
        version valid on the pricing date does not have (no row, or an empty
        rate): a rate that existed then is never replaced by a later one."""
        chain = await self.chain(org_id)
        for later in chain:
            if (later.valid_from, later.version) <= (v.valid_from, v.version):
                continue
            found = lookup(later)
            if usable(found):
                return found, later
        return None

    async def plant_name(self, plant_id: Optional[int]) -> Optional[str]:
        if plant_id is None:
            return None
        if getattr(self, "_plant_names", None) is None:
            self._plant_names = dict((await self.db.execute(
                select(Plant.id, Plant.name))).all())
        return self._plant_names.get(plant_id)

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
        v, earliest = await self.pricing_version(org_id, on_date)
        return Price(rate=None, currency=await self.plant_currency(plant_id),
                     source="cost_sheet", unit=unit,
                     version_id=v.id if v else None, version=v.version if v else None,
                     detail={"missing": [reason]})

    async def labour_price(self, org_id: Optional[int], department_id: int,
                           plant_id: Optional[int], position: Optional[str] = None,
                           on_date: Optional[date] = None) -> Price:
        """The effective labour rate (base + personnel overhead) of the
        version valid on on_date (the first version for a date before it);
        when that version has no rate for the department at the plant, the
        earliest later version that has one (gap fill, labelled).
        department_rate only for an org without a cost sheet."""
        on_date = on_date or business_today()
        if await self.has_cost_sheet(org_id):
            v, earliest = await self.pricing_version(org_id, on_date)

            def lookup(x):
                return cs.rate_in_version(x, department_id, position, plant_id,
                                          with_overhead=True)
            hit = lookup(v) if v else None
            filled = None
            if hit is None and v is not None:
                filled = await self.gap_fill(org_id, v, lookup)
                hit = filled[0] if filled else None
            if hit is None:
                return await self._no_hit(org_id, plant_id, on_date, "h", "labour_rate")
            return annotate(_from_hit(hit), v, earliest, filled)
        rate = await self.legacy_rate(department_id, plant_id)
        return Price(rate=rate, currency=await self.plant_currency(plant_id),
                     source="department_rate" if rate is not None else None,
                     detail={} if rate is not None else {"missing": ["labour_rate"]})

    async def machine_price(self, org_id: Optional[int], machine_class_id: Optional[int],
                            plant_id: Optional[int], on_date: Optional[date] = None,
                            machine_id: Optional[int] = None) -> Price:
        """A named machine's own rate beats the class rate; without one the
        class rate of the machine's plant (the costing plant when the machine
        maps to none) applies. Gap fill as labour_price: only when the
        version valid on the pricing date has neither."""
        on_date = on_date or business_today()
        m = await self.machine(machine_id)
        costing_cur = await self.plant_currency(plant_id)
        class_plant = (m.plant_id or plant_id) if m is not None else plant_id
        v, earliest = await self.pricing_version(org_id, on_date)

        def lookup(x):
            if m is not None:
                own = msvc.machine_rate_in_version(x, m.id)
                if own is not None:
                    return own, True
            if machine_class_id is None:
                return None
            hit = cs.machine_rate_in_version(x, machine_class_id, class_plant)
            return (hit, False) if hit is not None else None
        found = lookup(v) if v else None
        filled = None
        if found is None and v is not None:
            filled = await self.gap_fill(org_id, v, lookup)
            found = filled[0] if filled else None
        if found is None:
            if machine_class_id is None:
                return Price(rate=None, currency=await self.plant_currency(class_plant),
                             source=None, detail={"missing": ["machine_class"]})
            return await self._no_hit(org_id, class_plant, on_date, "h", "machine_rate")
        hit, own = found
        used = filled[1] if filled else v
        price = _from_hit(hit)
        if own:
            price.detail = {**price.detail, "machine_id": m.id}
        price = annotate(price, v, earliest, filled)
        # a named machine's plant may quote in another currency than the costing plant
        return in_costing_currency(price, used, costing_cur) if m is not None else price

    async def sampling_price(self, org_id: Optional[int], machine_class_id: Optional[int],
                             plant_id: Optional[int], on_date: Optional[date] = None,
                             machine_id: Optional[int] = None) -> Price:
        """The class's price of a trial; a named machine prices the machine
        hours of a components row at its own rate. Gap fill as labour_price
        when the version valid on the pricing date has no sampling row for
        the class, or its price lacks a rate (machine or labour). A row
        that lacks ONLY its labour rate keeps its hours, handling and
        machine rate and takes just the labour rate from the earliest later
        version that has it (labelled "no labour rate in v1 ...")."""
        on_date = on_date or business_today()
        m = await self.machine(machine_id)
        costing_cur = await self.plant_currency(plant_id)
        if m is not None:
            plant_id = m.plant_id or plant_id
        if machine_class_id is None:
            return Price(rate=None, currency=await self.plant_currency(plant_id),
                         source=None, unit="trial", detail={"missing": ["machine_class"]})
        v, earliest = await self.pricing_version(org_id, on_date)

        def lookup(x):
            hit = cs.sampling_in_version(x, machine_class_id, plant_id)
            if hit is not None and m is not None:
                hit = msvc.sampling_with_machine(hit, msvc.machine_rate_in_version(x, m.id), x)
            return hit
        hit = lookup(v) if v else None
        filled = None
        part = None
        if v is not None and _labour_only_gap(hit):
            # the row is there with its hours, handling and machine rate:
            # only the labour rate comes from the earliest later version
            row = next((r for r in v.sampling_rates if r.id == hit.row_id), None)
            if row is not None and row.labour_department_id:
                filled = await self.gap_fill(
                    org_id, v, lambda x: cs.rate_in_version(
                        x, row.labour_department_id, row.labour_position, plant_id,
                        with_overhead=True),
                    usable=lambda h: h is not None and h.rate is not None)
            if filled:
                hit, part = _with_labour_rate(hit, filled[0]), "labour_rate"
        if v is not None and filled is None and _sampling_gap(hit):
            filled = await self.gap_fill(org_id, v, lookup,
                                         usable=lambda h: not _sampling_gap(h))
            if filled:
                hit = filled[0]
        if hit is None:
            return await self._no_hit(org_id, plant_id, on_date, "trial", "sampling_rate")
        # a labour-only fill keeps the row (and its version): the machine
        # rate and its exchange rate are the creation-date version's
        used = filled[1] if filled and part is None else v
        price = annotate(_from_hit(hit, unit="trial"), v, earliest, filled, part=part)
        return in_costing_currency(price, used, costing_cur) if m is not None else price


def _sampling_gap(hit) -> bool:
    """No sampling price in the version: no row for the class, or a price
    that lacks a machine or labour rate there (a currency mismatch is not a
    gap: the rate exists)."""
    if hit is None:
        return True
    missing = set((hit.breakdown or {}).get("missing") or [])
    return hit.rate is None and bool(missing) and missing <= {"machine_rate", "labour_rate"}


def _labour_only_gap(hit) -> bool:
    """A components sampling row whose ONLY missing part is the labour rate
    (the machine rate and the currencies are fine)."""
    if hit is None or hit.rate is not None:
        return False
    b = hit.breakdown or {}
    return b.get("mode") == "components" and list(b.get("missing") or []) == ["labour_rate"]


def _with_labour_rate(hit, lhit):
    """The creation-date version's sampling price with the labour rate taken
    from a later version (lhit): setup / run hours, machine rate and cost,
    handling and labour hours stay the row's. A labour rate in another
    currency than the row is reported, not added."""
    b = dict(hit.breakdown or {})
    hours = float(b.get("labour_hours") or 0)
    missing = [m for m in (b.get("missing") or []) if m != "labour_rate"]
    if lhit.currency != hit.currency:
        missing.append("labour_rate_currency")
    labour_cost = round(hours * lhit.rate, 2) if not missing else 0.0
    price = None if missing else round(
        float(b.get("machine_cost") or 0) + labour_cost + float(b.get("handling_cost") or 0), 2)
    b.update({"labour_rate": lhit.rate, "labour_cost": labour_cost,
              "labour_rate_version": lhit.version, "labour_rate_version_id": lhit.version_id,
              "missing": missing, "complete": not missing})
    return cs.RateHit(rate=price, currency=hit.currency, version_id=hit.version_id,
                      version=hit.version, row_id=hit.row_id, match=hit.match,
                      base_rate=hit.base_rate, overhead=hit.overhead, breakdown=b)


def annotate(price: Price, v: Optional[CostSheetVersion], earliest: bool, filled,
             part: Optional[str] = None) -> Price:
    """Record why the price is not simply "the version valid on the pricing
    date": priced with the first version (the date lies before it), or taken
    from a later version because that one had no rate (gap fill). The
    snapshot keeps it (rate_detail), rate_label says it."""
    extra: dict = {}
    if earliest and v is not None:
        extra["earliest"] = True
    if filled:
        later = filled[1]
        extra["gap_fill"] = {"no_rate_in": v.version, "version": later.version,
                             "valid_from": later.valid_from.isoformat()
                             if later.valid_from else None,
                             **({"part": part} if part else {})}
    if extra:
        price.detail = {**price.detail, **extra}
    return price


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


def in_costing_currency(price: Price, v: Optional[CostSheetVersion], target: str) -> Price:
    """A named machine's rate (its own, or the class rate at its plant) in
    the costing plant's currency: converted at the version's exchange rate
    and labelled (detail["fx"]); without that rate it is not priced
    (missing machine_rate_currency), never added across currencies."""
    if price.rate is None or price.currency == target:
        return price
    converted = cs.convert(v, price.rate, price.currency, target)
    if converted is None:
        return Price(rate=None, currency=price.currency, source=price.source,
                     unit=price.unit, version_id=price.version_id, version=price.version,
                     match=price.match,
                     detail={**price.detail, "missing": [
                         *(price.detail.get("missing") or []), "machine_rate_currency"]})
    return Price(rate=converted, currency=target, source=price.source, unit=price.unit,
                 version_id=price.version_id, version=price.version, match=price.match,
                 detail={**price.detail, "fx": {
                     "from_currency": price.currency, "from_rate": price.rate,
                     "rate": str(cs.fx_rate(v, target, price.currency))}})


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
    """The line's price with the version valid on on_date (default: the
    change's creation date). A machine_time / sampling line without its own
    class is priced on the change's class (own or tonnage default); the class
    used is recorded in detail["machine_class_id"]."""
    book = book or RateBook(db)
    on_date = on_date or change_pricing_date(change)
    if plant_id is None:
        plant_id = await costing_plant_id(db, change)
    if org_id is None:
        org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    if p.kind in ("machine_time", "sampling"):
        # the line's own class, else the named machine's, else the change's
        machine_id = getattr(p, "machine_id", None)
        cls_id = (p.machine_class_id or await book.machine_class_of(org_id, machine_id)
                  or await change_machine_class_id(db, change, org_id))
        fn = book.machine_price if p.kind == "machine_time" else book.sampling_price
        price = await fn(org_id, cls_id, plant_id, on_date, machine_id=machine_id)
        if machine_id is not None:
            price.detail = {**price.detail, "machine_id": machine_id}
        if cls_id is not None:
            price.detail = {**price.detail, "machine_class_id": cls_id}
        return price
    return await book.labour_price(org_id, p.department_id, plant_id,
                                   p.labour_position, on_date)


async def snapshot_position(db: AsyncSession, change, p: CostingPosition,
                            on_date: Optional[date] = None) -> Price:
    """Price the line and store the snapshot on it (rate, rate currency,
    version). Called when a line is created or its pricing inputs change.
    Priced with the version valid on the change's creation date
    (change_pricing_date), whatever day the line is entered; rate_on is that
    date.

    A line with a class of its own keeps it; a line priced on the change's
    class keeps machine_class_id None (so a later change of the class moves
    it) and records the class used in rate_detail. A line that found no rate
    stores no snapshot (rate_on None): it is priced live until a rate exists.
    The money currency (p.currency, of est_cost and offers) is the costing
    plant's and is not the rate's business."""
    on_date = on_date or change_pricing_date(change)
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
    """The snapshot, or for a line without one, the rate valid on the
    change's creation date (read only: GETs never write)."""
    return stored_price(p) or await price_for_position(
        db, change, p, org_id=org_id, plant_id=plant_id, book=book)


def line_value(p: CostingPosition, price: Price) -> Optional[float]:
    """hours x rate / trials x price; None = cannot price (never 0); 0.0
    when there is nothing to price."""
    return amount_of(quantity(p), price)


def amount_of(q: float, price: Optional[Price]) -> Optional[float]:
    """q x the price's rate, rounded to cents once. A rate converted from
    another currency (detail["fx"]) is multiplied in its own currency first
    and the product converted, so the cents are not rounded twice."""
    if not q:
        return 0.0
    if price is None or price.rate is None:
        return None
    fx = (price.detail or {}).get("fx")
    if fx and fx.get("rate") not in (None, "") and fx.get("from_rate") is not None:
        rate = Decimal(str(fx["rate"]))
        if rate:
            return float((Decimal(str(q)) * Decimal(str(fx["from_rate"])) / rate)
                         .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
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
        machine = await book.machine(getattr(p, "machine_id", None))
        machine_name = machine.internal_name if machine is not None else None
        # the line's own class, else the change's class it was priced on
        used_cls = p.machine_class_id or price.detail.get("machine_class_id")
        cls = classes.get(used_cls) if used_cls else None
        out[p.id] = {
            "rate": price.rate, "rate_currency": price.currency,
            "currency": p.currency or money_currency,
            # an old line without a recorded currency: shown in the costing
            # plant's currency and flagged, never read as one silently
            "currency_unrecorded": p.currency is None,
            "machine_class_used_id": used_cls,
            "machine_class_from_change": bool(
                p.kind in ("machine_time", "sampling") and used_cls
                and not p.machine_class_id and machine is None),
            "machine_id": getattr(p, "machine_id", None),
            "machine_name": machine_name,
            # priced on the machine's own rate (else its class rate)
            "machine_rate_own": price.match == "machine",
            "rate_unit": price.unit, "rate_source": price.source,
            "cost_sheet_version_id": price.version_id,
            "cost_sheet_version": price.version,
            "rate_match": price.match, "rate_on": p.rate_on,
            "rate_label": rate_label(
                price, department=names.get(p.department_id),
                position=p.labour_position,
                machine_class=((machine_name if price.match == "machine" else cls)
                               if p.kind in ("machine_time", "sampling") else None)),
            "rate_missing": price.rate is None and quantity(p) > 0,
            "rate_missing_reason": (price.detail.get("missing") or [None])[0]
            if price.rate is None else None,
            "rate_is_snapshot": p.rate_on is not None,
            "line_value": value,
            "machine_class": cls,
        }
    return out


PRICING_FIELDS = ("kind", "hours", "labour_position", "machine_class_id", "trials",
                  "machine_id")


def is_labour(kind: str) -> bool:
    return kind in LABOUR_KINDS


# ---------------------------------------------------------------- context API

async def costing_context(db: AsyncSession, change) -> dict:
    """What the costing table needs besides the lines: the costing plant and
    its currency, the cost sheet version that prices the change (valid on
    its creation date, pricing_date) and whether the sheet owes a review, the machine classes with the change's class (own or the
    tonnage default), and the positions each department has a rate for."""
    plant_id = await costing_plant_id(db, change)
    org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    plant = await db.get(Plant, plant_id) if plant_id is not None else None
    sheet = await has_cost_sheet(db, org_id)
    pricing_date = change_pricing_date(change)
    # the version that prices this change: valid on its creation date
    current = (await cs.pricing_version(db, org_id, pricing_date)
               if org_id is not None else None)
    earliest = (current is not None and current.valid_from is not None
                and current.valid_from > pricing_date)
    latest = await cs.latest_published(db, org_id) if org_id is not None else None
    classes = await cs.list_machine_classes(db, org_id) if org_id is not None else []
    default_cls, tonnage = await default_machine_class(db, org_id, change)
    effective = change.machine_class_id or (default_cls.id if default_cls else None)
    # Rates are one per department per plant (104): no labour positions to
    # offer any more. The key stays (empty) for older clients.
    positions: dict[int, list[str]] = {}
    stale = await cs.stale_status(db, org_id) if (org_id is not None and sheet) else None
    return {
        "plant_id": plant_id,
        "plant_name": plant.name if plant else None,
        "currency": await cs.plant_currency(db, plant_id),
        # the plant's second currency (Silao: MXN) and the change's version's
        # exchange rates: money entered in it is converted at that rate
        "local_currency": plant.local_currency if plant is not None else None,
        "fx_rates": cs.fx_list(current),
        "rate_source": "cost_sheet" if sheet else "department_rate",
        "current_version": ({"id": current.id, "version": current.version,
                             "valid_from": current.valid_from} if current else None),
        "pricing_date": pricing_date,
        # the change is older than the first version: priced with that one
        "pricing_note": (f"priced with v{current.version}, the earliest cost sheet"
                         if earliest else None),
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
    """Each implementation booking priced on booking_pricing_date (the
    booking date for now, see BOOKING_PRICING_BASIS): hours x the effective
    labour rate (department, the costing plant) valid that day, plus machine
    hours x the machine class rate valid that day. A value None = cannot
    price (never 0)."""
    if plant_id is None:
        plant_id = await costing_plant_id(db, change)
    if org_id is None:
        org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    book = book or RateBook(db)
    labour: dict[tuple, Price] = {}
    machine: dict[tuple, Price] = {}
    out = []
    for b in bookings:
        on = booking_pricing_date(change, b.booked_at)
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
            "labour_value": amount_of(hours, lp),
            "machine_hours": mh,
            "machine_rate": mp.rate if mp else None,
            "machine_currency": mp.currency if mp else None,
            "machine_value": amount_of(mh, mp) if mp else 0.0,
        })
    return out


# ---------------------------------------------------------------- warnings

async def costing_versions(db: AsyncSession, change) -> list[int]:
    """The cost sheet version numbers the change's costing lines were
    priced with (position snapshots and cost lines)."""
    from app.models.change import ChangeAssessment
    from app.models.change_cost import AssessmentCostLine
    # a line priced from a later version because the change's own version
    # had no rate for it (gap fill) is priced as the rule says: not outdated.
    # Only while that version is still the change's own: a version published
    # later (backdated) may have the rate now, and then the line is outdated.
    org_id = await change_org_id(db, change)
    book = RateBook(db)
    current, _ = await book.pricing_version(org_id, change_pricing_date(change))
    nums = {v for v, detail in (await db.execute(
        select(CostingPosition.cost_sheet_version, CostingPosition.rate_detail).where(
            CostingPosition.change_id == change.id,
            CostingPosition.cost_sheet_version.is_not(None)))).all()
        if not position_gap_filled(current, detail)}
    rows = (await db.execute(
        select(AssessmentCostLine.cost_sheet_version_id, ChangeAssessment.department_id,
               AssessmentCostLine.plant_id)
        .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
        .where(ChangeAssessment.change_id == change.id,
               AssessmentCostLine.cost_sheet_version_id.is_not(None)))).all()
    chain = await book.chain(org_id) if rows else []
    ids = {vid for vid, dep, plant in rows
           if not cost_line_gap_filled(current, vid, dep, plant, chain)}
    if ids:
        nums |= set((await db.execute(select(CostSheetVersion.version).where(
            CostSheetVersion.id.in_(ids)))).scalars().all())
    return sorted(nums)


def position_gap_filled(current: Optional[CostSheetVersion], detail: Optional[dict]) -> bool:
    """A costing position whose snapshot was gap filled FROM the change's
    current pricing version (rate_detail.gap_fill.no_rate_in is it): priced
    as the rule says, not outdated. A gap fill recorded against another
    version (a backdated version published since) counts as outdated."""
    gap = (detail or {}).get("gap_fill")
    return bool(gap) and current is not None and gap.get("no_rate_in") == current.version


def cost_line_gap_filled(current: Optional[CostSheetVersion], version_id: Optional[int],
                         department_id: int, plant_id: Optional[int],
                         chain: list[CostSheetVersion]) -> bool:
    """A cost line priced with another version than the change's own, where
    the change's own has no rate for the department at the plant AND the
    line's version is exactly the one the gap fill would choose now (the
    earliest later published version with a rate, `chain` in validity
    order): priced as the rule says, not outdated. Anything else counts
    toward the outdated warning."""
    if current is None or version_id is None or version_id == current.id:
        return False
    if cs.rate_in_version(current, department_id, None, plant_id) is not None:
        return False
    for later in chain:
        if (later.valid_from, later.version) <= (current.valid_from, current.version):
            continue
        if cs.rate_in_version(later, department_id, None, plant_id) is not None:
            return later.id == version_id
    return False


# ---------------------------------------------------------------- exchange

async def change_fx_version(db: AsyncSession, change, *, org_id: Optional[int] = None,
                            book: Optional["RateBook"] = None) -> Optional[CostSheetVersion]:
    """The version whose exchange rates convert this change's money: the one
    valid on its creation date, like its rates."""
    if org_id is None:
        plant_id = await costing_plant_id(db, change)
        org_id = (await org_id_of_plant(db, plant_id)) or await change_org_id(db, change)
    v, _ = await (book or RateBook(db)).pricing_version(org_id, change_pricing_date(change))
    return v


def fx_note(conv: dict) -> str:
    """'1,730.00 MXN of actual costs converted to 100.00 USD at 17.30 MXN per
    USD (cost sheet v3)': every conversion is said, with its rate."""
    rate = conv["rate"]
    text = fmt_fx(rate)
    return (f"{fmt_number(conv['amount'], 2)} {conv['currency']} of actual costs converted "
            f"to {fmt_number(conv['converted'], 2)} {conv['to']} at {text} "
            f"{conv['currency']} per {conv['to']} (cost sheet v{conv['version']})")


def outdated_message(old: list[int], current: int) -> str:
    """The one wording for "a line was priced with another version than the
    change's own" (costing, P&L, offers)."""
    return (f"Costing used cost sheet {', '.join(f'v{v}' for v in old)}; this change "
            f"is priced with v{current} (valid on its creation date)")


async def version_warning(db: AsyncSession, change, used: Optional[list[int]] = None
                          ) -> Optional[str]:
    """outdated_message when a costing line was priced with another version
    than the one valid on the change's creation date (a line priced before
    that rule, or before a backdated version was published). A version
    published later for later dates is no reason to warn: it never applies
    to this change."""
    org_id = await change_org_id(db, change)
    if org_id is None:
        return None
    current = await cs.pricing_version(db, org_id, change_pricing_date(change))
    if current is None:
        return None
    used = used if used is not None else await costing_versions(db, change)
    old = [v for v in used if v != current.version]
    if not old:
        return None
    return outdated_message(old, current.version)


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
