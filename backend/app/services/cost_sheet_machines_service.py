"""MachineDB presses in the cost sheet: sync, plant mapping, per-machine rates.

- sync_machines pulls MachineDB's machine list into cost_sheet_machines. It
  is idempotent: a second run with the same MachineDB data reports nothing
  new or changed. A machine MachineDB stops listing is retired (kept, since
  rates and costing lines point at it); a machine past its planned scrap
  date is inactive. MachineDB plants map to plm2 plants through an explicit
  mapping (org setting machinedb_plant_map, merged key by key) with a
  small default by plant name; a MachineDB plant nothing maps to is listed
  in the report, never guessed. An answer that looks broken (empty, mostly
  unreadable, most machines gone) is refused unless forced (sync_guard).
- set_machine_rate writes one machine's hourly rate into the open draft
  (one row per machine per version); published versions stay frozen.
- machine_rate_in_version is the lookup costing uses: a line that names a
  machine is priced on the machine's own rate, else on the class rate of
  the machine's plant (cost_sheet_service.machine_rate_in_version).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cost_sheet import CostSheetVersion
from app.models.cost_sheet_machines import (
    CostSheetMachine, CostSheetMachineItemRate, SETTING_MACHINEDB_ENABLED,
    SETTING_MACHINEDB_LAST_SYNC, SETTING_MACHINEDB_PLANT_MAP,
)
from app.models.entities import Plant
from app.services import cost_sheet_service as cs
from app.services import machinedb_client
from app.services.cost_sheet_service import CostSheetError, RateHit
from app.utils.clock import business_today

logger = logging.getLogger(__name__)

SYNC_DEPARTMENTS = ("Finance", "Sales")

# MachineDB plant key -> words that identify the plm2 plant (a whole word of
# its name, location or code). Only these three are known; any other
# MachineDB plant stays unmapped until someone maps it.
DEFAULT_PLANT_HINTS: dict[str, tuple[str, ...]] = {
    "usa": ("toccoa", "usa"),
    "mexico": ("silao", "mexico"),
    "weissenburg": ("weissenburg",),
}

# The fields a sync copies; a difference in any of them is a "changed".
_SYNC_FIELDS = ("internal_name", "machinedb_plant", "plant_id", "clamping_force_t",
                "tonnage_class", "two_k_type", "manufacturer", "model",
                "in_service_from", "planned_scrap_from", "active")


# ---------------------------------------------------------------- rights

async def can_sync(db: AsyncSession, user) -> bool:
    """Admins (not acting as a department) and members of Finance or Sales,
    acts-as aware."""
    from app.models.workflow import Department
    from app.services.workflow_service import WorkflowService
    if getattr(user, "acts_as_department_id", None) is None and user.role == "admin":
        return True
    ids = set((await db.execute(select(Department.id).where(
        Department.name.in_(SYNC_DEPARTMENTS)))).scalars().all())
    return bool(ids & set(await WorkflowService.effective_department_ids(db, user)))


# ---------------------------------------------------------------- plant mapping

def _words(*texts: Optional[str]) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out |= {w for w in re.split(r"[^a-z0-9]+", (t or "").casefold()) if w}
    return out


def default_plant_for(key: str, plants: Iterable[Plant]) -> tuple[Optional[int], str]:
    """(plant id, why) by the default hints: exactly one plant must match."""
    hints = DEFAULT_PLANT_HINTS.get(key)
    if not hints:
        return None, "no default for this MachineDB plant"
    hits = [p for p in plants if _words(p.name, p.location, p.code) & set(hints)]
    if len(hits) == 1:
        return hits[0].id, "default"
    if not hits:
        return None, "no plant matches"
    return None, "several plants match"


async def configured_plant_map(db: AsyncSession, org_id: int) -> dict[str, Optional[int]]:
    raw = await cs.get_setting(db, org_id, SETTING_MACHINEDB_PLANT_MAP)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("org %s: unreadable %s, ignored", org_id, SETTING_MACHINEDB_PLANT_MAP)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).casefold(): (int(v) if isinstance(v, int) else None)
            for k, v in data.items()}


async def _org_plants(db: AsyncSession, org_id: int) -> list[Plant]:
    return list((await db.execute(select(Plant).where(
        Plant.organization_id == org_id).order_by(Plant.id))).scalars().all())


async def plant_map(db: AsyncSession, org_id: int,
                    keys: Iterable[str] = ()) -> dict[str, dict]:
    """{machinedb plant: {plant_id, source}} for the known keys plus `keys`:
    source 'setting' (mapped by hand, null = deliberately unmapped),
    'default' (by plant name), or the reason nothing maps."""
    plants = await _org_plants(db, org_id)
    valid = {p.id for p in plants}
    conf = await configured_plant_map(db, org_id)
    out: dict[str, dict] = {}
    for key in sorted(set(DEFAULT_PLANT_HINTS) | set(conf) | {k for k in keys if k}):
        if key in conf and (conf[key] is None or conf[key] in valid):
            out[key] = {"plant_id": conf[key], "source": "setting"}
        else:
            pid, why = default_plant_for(key, plants)
            out[key] = {"plant_id": pid, "source": why}
    return out


async def _stored_plant_map(db: AsyncSession, org_id: int) -> dict[str, Optional[int]]:
    """The hand mapping exactly as stored (keys casefolded)."""
    return dict(await configured_plant_map(db, org_id))


async def _save_plant_map(db: AsyncSession, org_id: int, stored: dict[str, Optional[int]],
                          user_id: Optional[int]) -> dict[str, dict]:
    text = json.dumps(dict(sorted(stored.items())), separators=(",", ":"))
    if len(text) > 255:                      # org_settings.value is String(255)
        raise CostSheetError("Too many plant mappings", 422)
    await cs.set_setting(db, org_id, SETTING_MACHINEDB_PLANT_MAP,
                         text if stored else None, user_id)
    effective = await plant_map(db, org_id)
    for m in (await db.execute(select(CostSheetMachine).where(
            CostSheetMachine.organization_id == org_id))).scalars().all():
        entry = effective.get(m.machinedb_plant or "")
        m.plant_id = entry["plant_id"] if entry else None
    await db.flush()
    return effective


def _map_key(k) -> str:
    key = str(k).strip().casefold()
    if not key or len(key) > 40:
        raise CostSheetError("Unknown MachineDB plant", 422)
    return key


async def set_plant_map(db: AsyncSession, org_id: int, mapping: dict,
                        user_id: Optional[int]) -> dict[str, dict]:
    """Merge `mapping` into the stored hand mapping: a MachineDB plant key
    maps to a plant id of the org, or to None = deliberately unmapped. Keys
    not named keep their stored value (unmap_plant drops one so the default
    applies again). Machines already synced move with it."""
    plants = {p.id for p in await _org_plants(db, org_id)}
    stored = await _stored_plant_map(db, org_id)
    for k, v in mapping.items():
        key = _map_key(k)
        if v is not None and v not in plants:
            raise CostSheetError("Unknown plant", 422)
        stored[key] = v
    return await _save_plant_map(db, org_id, stored, user_id)


async def unmap_plant(db: AsyncSession, org_id: int, key: str,
                      user_id: Optional[int]) -> dict[str, dict]:
    """Drop one hand mapping: the MachineDB plant is mapped by the default
    (by plant name) again, or stays unmapped when no default applies."""
    stored = await _stored_plant_map(db, org_id)
    if stored.pop(_map_key(key), "absent") == "absent":
        raise CostSheetError("This MachineDB plant has no hand mapping", 404)
    return await _save_plant_map(db, org_id, stored, user_id)


# ---------------------------------------------------------------- sync

# Clamping force bound (t): Numeric(10, 2) holds less than 1e8; the largest
# presses are far below this.
MAX_CLAMPING_FORCE_T = 100_000


def machine_active(planned_scrap_from: Optional[date], retired: bool,
                   today: Optional[date] = None) -> bool:
    """Not retired from MachineDB and not scrapped (planned_scrap_from not
    reached)."""
    today = today or business_today()
    return not retired and (planned_scrap_from is None or planned_scrap_from > today)


async def last_sync(db: AsyncSession, org_id: int) -> Optional[dict]:
    raw = await cs.get_setting(db, org_id, SETTING_MACHINEDB_LAST_SYNC)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def _store_last_sync(db: AsyncSession, org_id: int, summary: dict,
                           user_id: Optional[int]) -> None:
    text = json.dumps(summary, separators=(",", ":"), ensure_ascii=False)
    if len(text) > 255:                      # org_settings.value is String(255)
        # shorten the error, never the JSON (a cut JSON would read as no sync)
        err = summary.get("error") or ""
        cut = max(0, len(err) - (len(text) - 255))
        summary = {**summary, "error": err[:cut] or None}
        text = json.dumps(summary, separators=(",", ":"), ensure_ascii=False)
        if len(text) > 255:
            text = json.dumps({k: summary.get(k) for k in ("at", "failed_at", "total")},
                              separators=(",", ":"))
    await cs.set_setting(db, org_id, SETTING_MACHINEDB_LAST_SYNC, text, user_id)


def _entry(m: CostSheetMachine, **extra) -> dict:
    return {"machinedb_id": m.machinedb_id, "internal_name": m.internal_name,
            "machinedb_plant": m.machinedb_plant, "plant_id": m.plant_id, **extra}


# A sync that would empty or gut the local copy is refused unless forced:
# more than this share of the rows unreadable, or of the machines retired.
SYNC_GUARD_SHARE = 0.5


async def _record_failure(db: AsyncSession, org_id: int, now: datetime, error: str,
                          user_id: Optional[int], **extra) -> None:
    """Keep the last good sync's counts and add the failed attempt."""
    prev = await last_sync(db, org_id) or {}
    await _store_last_sync(db, org_id, {
        **{k: prev.get(k) for k in ("at", "total", "new", "changed", "retired",
                                    "unmapped") if k in prev},
        "failed_at": now.isoformat(timespec="seconds"), "error": error, **extra}, user_id)


def sync_guard(machines: list, skipped: list, existing: dict) -> Optional[str]:
    """Why this MachineDB answer looks broken rather than real (None = fine):
    an empty list while machines are on record, more than half of the rows
    unreadable, or more than half of the machines on record retired at once."""
    live = [r for r in existing.values() if r.retired_at is None]
    ids = {m.id for m in machines}
    rows = len(machines) + len(skipped)
    if not machines and live:
        return (f"MachineDB listed no machines while {len(live)} are on record; "
                "nothing was changed")
    if rows and len(skipped) > rows * SYNC_GUARD_SHARE:
        return (f"MachineDB sent {len(skipped)} unreadable rows of {rows}; "
                "nothing was changed")
    gone = [r for mid, r in existing.items() if mid not in ids and r.retired_at is None]
    if live and len(gone) > len(live) * SYNC_GUARD_SHARE:
        return (f"The sync would retire {len(gone)} of {len(live)} machines; "
                "nothing was changed")
    return None


async def sync_machines(db: AsyncSession, org_id: int, user_id: Optional[int] = None, *,
                        machines: Optional[list] = None,
                        skipped: Optional[list[str]] = None,
                        today: Optional[date] = None, force: bool = False) -> dict:
    """Pull MachineDB into cost_sheet_machines and report what moved.

    `machines` (MachineDTOs) replaces the HTTP call in tests. Raises
    CostSheetError 503 when MachineDB is not configured or not reachable,
    and 409 when the answer looks broken (sync_guard) unless `force` (a
    manual sync by Sales, Finance or an admin; the startup sync never
    forces). A failure is recorded as the last sync attempt and the local
    copy is left as it was."""
    now = datetime.utcnow()
    today = today or business_today()
    if machines is None:
        try:
            machines, skipped = await machinedb_client.list_machines()
        except machinedb_client.MachineDBUnavailable as e:
            await _record_failure(db, org_id, now, str(e), user_id)
            raise CostSheetError(str(e), 503)
    skipped = list(skipped or [])
    existing = {m.machinedb_id: m for m in (await db.execute(select(CostSheetMachine).where(
        CostSheetMachine.organization_id == org_id))).scalars().all()}
    if not force:
        why = sync_guard(machines, skipped, existing)
        if why:
            await _record_failure(db, org_id, now, why, user_id, guard=True)
            raise CostSheetError(why + ". Check MachineDB, or sync again with force.", 409)
    mapping = await plant_map(db, org_id, keys={m.plant for m in machines if m.plant})
    report: dict = {"new": [], "changed": [], "retired": [], "scrapped": [], "returned": [],
                    "unmapped": [], "skipped": skipped}
    unmapped: dict[str, list[str]] = {}
    seen: set[int] = set()
    for dto in machines:
        if dto.id in seen:
            skipped.append(f"duplicate id {dto.id}")
            continue
        seen.add(dto.id)
        force_t = dto.clamping_force_t
        if force_t is not None and not (0 <= force_t < MAX_CLAMPING_FORCE_T):
            # a number the column cannot hold (or no press has): the row is
            # reported as skipped and left as it was, never a failed sync;
            # it stays in `seen`, so a known press is not retired for it
            skipped.append(f"{dto.internal_name} (id {dto.id}): clamping force "
                           f"{force_t:g} t out of range")
            continue
        entry = mapping.get(dto.plant or "")
        plant_id = entry["plant_id"] if entry else None
        if plant_id is None:
            unmapped.setdefault(dto.plant or "(none)", []).append(dto.internal_name)
        values = {
            "internal_name": dto.internal_name, "machinedb_plant": dto.plant,
            "plant_id": plant_id,
            "clamping_force_t": (round(dto.clamping_force_t, 2)
                                 if dto.clamping_force_t is not None else None),
            "tonnage_class": dto.tonnage_class, "two_k_type": dto.two_k_type,
            "manufacturer": dto.manufacturer, "model": dto.model,
            "in_service_from": dto.in_service_from,
            "planned_scrap_from": dto.planned_scrap_from,
            "active": machine_active(dto.planned_scrap_from, False, today),
        }
        row = existing.get(dto.id)
        if row is None:
            row = CostSheetMachine(organization_id=org_id, machinedb_id=dto.id,
                                   synced_at=now, source_updated_at=dto.updated_at, **values)
            db.add(row)
            report["new"].append(_entry(row))
            continue
        was_active, was_retired = row.active, row.retired_at is not None
        changed = [f for f in _SYNC_FIELDS if _norm(getattr(row, f)) != _norm(values[f])]
        for f in _SYNC_FIELDS:
            setattr(row, f, values[f])
        row.retired_at = None
        row.source_updated_at = dto.updated_at
        row.synced_at = now
        if was_retired:
            report["returned"].append(_entry(row))
        elif was_active and not row.active:
            report["scrapped"].append(_entry(row, planned_scrap_from=(
                row.planned_scrap_from.isoformat() if row.planned_scrap_from else None)))
        elif changed:
            report["changed"].append(_entry(row, fields=changed))
    for mid, row in existing.items():
        if mid not in seen and row.retired_at is None:
            row.retired_at = now
            row.active = False
            report["retired"].append(_entry(row))
    report["unmapped"] = [{"machinedb_plant": k, "count": len(v), "machines": sorted(v)[:20]}
                          for k, v in sorted(unmapped.items())]
    await db.flush()
    summary = {"at": now.isoformat(timespec="seconds"), "total": len(seen),
               "new": len(report["new"]), "changed": len(report["changed"]),
               "retired": len(report["retired"]) + len(report["scrapped"]),
               "unmapped": sum(u["count"] for u in report["unmapped"])}
    await _store_last_sync(db, org_id, summary, user_id)
    return {**summary, "report": report}


def _norm(v):
    if isinstance(v, float):
        return round(v, 2)
    return v


# ---------------------------------------------------------------- rates

def item_rate(v: Optional[CostSheetVersion], machine_id: int) -> Optional[CostSheetMachineItemRate]:
    if v is None:
        return None
    return next((r for r in v.machine_item_rates if r.machine_id == machine_id), None)


def machine_rate_in_version(v: CostSheetVersion, machine_id: int) -> Optional[RateHit]:
    """The machine's own hourly rate in the version, or None."""
    row = item_rate(v, machine_id)
    if row is None:
        return None
    r = round(float(row.hourly_rate), 2)
    return RateHit(rate=r, currency=row.currency, version_id=v.id, version=v.version,
                   row_id=row.id, match="machine", base_rate=r)


def sampling_with_machine(hit: RateHit, own: Optional[RateHit],
                          v: Optional[CostSheetVersion] = None) -> RateHit:
    """A components sampling price with the machine hours at the named
    machine's own rate instead of the class rate. Flat prices, rows without
    machine hours and machines without an own rate stay as they are; a
    machine rate in another currency than the row is converted at the
    version's exchange rate (recorded in breakdown["machine_rate_fx"]), and
    without one it is reported, not added."""
    b = hit.breakdown or {}
    hours = float(b.get("setup_hours") or 0) + float(b.get("run_hours") or 0)
    if own is None or b.get("mode") != "components" or not hours:
        return hit
    missing = [x for x in (b.get("missing") or [])
               if x not in ("machine_rate", "machine_rate_currency")]
    own_rate, fx = own.rate, None
    machine_cost = round(hours * own.rate, 2)
    if own.currency != hit.currency:
        # the hours are multiplied first and the product converted once,
        # so the cents are rounded one time only
        own_rate = cs.convert(v, own.rate, own.currency, hit.currency)
        converted = cs.convert(v, hours * own.rate, own.currency, hit.currency)
        if own_rate is None or converted is None:
            missing.append("machine_rate_currency")
            own_rate = own.rate
        else:
            machine_cost = converted
            fx = {"from_currency": own.currency, "from_rate": own.rate,
                  "rate": str(cs.fx_rate(v, hit.currency, own.currency))}
    price = None if missing else round(
        machine_cost + float(b.get("labour_cost") or 0) + float(b.get("handling_cost") or 0), 2)
    return RateHit(rate=price, currency=hit.currency, version_id=hit.version_id,
                   version=hit.version, row_id=hit.row_id, match=hit.match + "+machine",
                   breakdown={**b, "machine_rate": own_rate, "machine_cost": machine_cost,
                              "machine_rate_row_id": own.row_id,
                              **({"machine_rate_fx": fx} if fx else {}),
                              "missing": missing, "complete": not missing})


async def get_machine(db: AsyncSession, org_id: int, machine_id: int) -> CostSheetMachine:
    m = await db.get(CostSheetMachine, machine_id)
    if m is None or m.organization_id != org_id:
        raise CostSheetError("Unknown machine", 404)
    return m


async def set_machine_rate(db: AsyncSession, v: CostSheetVersion, machine_id: int, *,
                           hourly_rate: Optional[float] = None,
                           currency: Optional[str] = None, note=...,
                           entered_rate=..., entered_currency: Optional[str] = None
                           ) -> Optional[CostSheetMachineItemRate]:
    """Set (or with hourly_rate None remove) the machine's rate in a draft.

    Like a rate row of a two-currency plant (106): the rate may be typed in
    the machine plant's local currency (entered_rate + entered_currency);
    the typed number is kept and hourly_rate, in the row's currency, is
    computed at the version's exchange rate. A rate typed as hourly_rate
    clears the typed local one. note ... keeps the stored note."""
    cs._require_draft(v)
    m = await get_machine(db, v.organization_id, machine_id)
    row = item_rate(v, m.id)
    typed_local = entered_rate is not ...
    if (entered_rate if typed_local else hourly_rate) is None:
        if row is not None:
            await db.delete(row)
            await db.flush()
            await db.refresh(v)
        return None
    if currency:
        cur = cs.normalize_currency(currency)
    elif row is not None:
        cur = row.currency
    elif m.plant_id is not None:
        cur = await cs.plant_currency(db, m.plant_id)
    else:
        # an unmapped machine has no plant currency to fall back on: never
        # guess EUR for a press that may run in USD
        raise CostSheetError(
            "This machine is not mapped to a plant: choose the currency of its rate", 422)
    ent, ecur = None, None
    if typed_local:
        ecur = cs.normalize_currency(entered_currency or cur)
        typed = cs._check_number("entered_rate", entered_rate, 0, 1e10)
        if ecur == cur:
            rate = cs._check_number("hourly_rate", typed, *cs.BOUNDS["hourly_rate"])
            ecur = None
        else:
            plant = await db.get(Plant, m.plant_id) if m.plant_id else None
            if plant is None or plant.local_currency != ecur:
                raise CostSheetError(
                    f"{ecur} is not the local currency of this machine's plant: type the "
                    f"rate in {cur}", 422)
            quote = plant.currency or "EUR"
            if cur != quote:
                raise CostSheetError(
                    f"This rate is in {cur}, not {plant.name}'s quote currency {quote}: "
                    f"switch it to {quote} first, then type the rate in {ecur}", 422)
            conv = cs._from_entered(v, typed, cur, ecur)
            if conv is None:
                raise CostSheetError(
                    f"Enter the {cur}/{ecur} exchange rate of this version first", 422)
            rate = cs._check_number("hourly_rate", conv, *cs.BOUNDS["hourly_rate"])
            ent = typed
    else:
        rate = cs._check_number("hourly_rate", hourly_rate, *cs.BOUNDS["hourly_rate"])
    if note is ...:
        note = row.note if row is not None else None
    note = (note or "").strip()[:2000] or None
    if row is None:
        row = CostSheetMachineItemRate(version_id=v.id, machine_id=m.id,
                                       hourly_rate=rate, currency=cur, note=note,
                                       entered_rate=ent, entered_currency=ecur)
        db.add(row)
    else:
        row.hourly_rate, row.currency, row.note = rate, cur, note
        row.entered_rate, row.entered_currency = ent, ecur
    await db.flush()
    await db.refresh(v)
    return row


# ---------------------------------------------------------------- listing

async def list_machines(db: AsyncSession, org_id: int, *,
                        version: Optional[CostSheetVersion] = None,
                        plant_id: Optional[int] = None, active_only: bool = False,
                        min_tonnage: Optional[float] = None,
                        max_tonnage: Optional[float] = None) -> list[dict]:
    """The synced machines with their cost sheet class (from the tonnage),
    their own rate in `version` and the class rate of their plant there."""
    q = select(CostSheetMachine).where(CostSheetMachine.organization_id == org_id)
    if plant_id is not None:
        q = q.where(CostSheetMachine.plant_id == plant_id)
    if active_only:
        q = q.where(CostSheetMachine.active.is_(True))
    if min_tonnage is not None:
        q = q.where(CostSheetMachine.clamping_force_t >= min_tonnage)
    if max_tonnage is not None:
        q = q.where(CostSheetMachine.clamping_force_t <= max_tonnage)
    rows = (await db.execute(q.order_by(CostSheetMachine.plant_id, CostSheetMachine.clamping_force_t,
                                        CostSheetMachine.internal_name))).scalars().all()
    classes = await cs.list_machine_classes(db, org_id)
    by_name = {c.name: c for c in classes}
    org_plants = await _org_plants(db, org_id)
    plant_cur = {p.id: (p.currency or "EUR") for p in org_plants}
    plant_local = {p.id: p.local_currency for p in org_plants if p.local_currency}
    out = []
    for m in rows:
        cls_name = (cs.class_for_tonnage(classes, float(m.clamping_force_t))
                    if m.clamping_force_t is not None else None)
        cls = by_name.get(cls_name) if cls_name else None
        own = item_rate(version, m.id)
        class_hit = (cs.machine_rate_in_version(version, cls.id, m.plant_id)
                     if version is not None and cls is not None else None)
        out.append({
            "id": m.id, "machinedb_id": m.machinedb_id, "internal_name": m.internal_name,
            "machinedb_plant": m.machinedb_plant, "plant_id": m.plant_id,
            "clamping_force_t": m.clamping_force_t, "tonnage_class": m.tonnage_class,
            "two_k_type": m.two_k_type, "manufacturer": m.manufacturer, "model": m.model,
            "in_service_from": m.in_service_from.isoformat() if m.in_service_from else None,
            "planned_scrap_from": (m.planned_scrap_from.isoformat()
                                   if m.planned_scrap_from else None),
            # the currency a new own rate defaults to; None = unmapped, the
            # editor must choose one
            "plant_currency": plant_cur.get(m.plant_id) if m.plant_id else None,
            "active": m.active, "retired": m.retired_at is not None,
            "synced_at": m.synced_at.isoformat() if m.synced_at else None,
            "machine_class_id": cls.id if cls else None,
            "machine_class": cls.name if cls else None,
            "rate_id": own.id if own else None,
            "hourly_rate": float(own.hourly_rate) if own else None,
            "currency": own.currency if own else None,
            "note": own.note if own else None,
            "entered_rate": (float(own.entered_rate) if own and own.entered_currency
                             and own.entered_rate is not None else None),
            "entered_currency": own.entered_currency if own else None,
            # the two-currency view of the rates tab: the rate in the plant's
            # local currency (typed there, or converted) and which was typed
            **_dual(version, own, plant_cur.get(m.plant_id), plant_local.get(m.plant_id)),
            "class_rate": class_hit.rate if class_hit else None,
            "class_rate_currency": class_hit.currency if class_hit else None,
        })
    return out


def _dual(v: Optional[CostSheetVersion], own: Optional[CostSheetMachineItemRate],
          quote: Optional[str], local: Optional[str]) -> dict:
    """local_currency / local_rate / entered_in of a machine at a plant with
    a second currency; the local column shows even before a rate exists."""
    if not local or local == (own.currency if own else quote):
        return {"local_currency": None, "local_rate": None, "entered_in": None}
    if own is None:
        return {"local_currency": local, "local_rate": None, "entered_in": None}
    return cs.dual_view(v, own, local)


async def machine_class_id_for(db: AsyncSession, org_id: Optional[int],
                               m: CostSheetMachine) -> Optional[int]:
    """The cost sheet class the machine's tonnage falls in."""
    if org_id is None or m.clamping_force_t is None:
        return None
    classes = await cs.list_machine_classes(db, org_id)
    name = cs.class_for_tonnage(classes, float(m.clamping_force_t))
    return next((c.id for c in classes if c.name == name), None)


# ---------------------------------------------------------------- startup

def _truthy(value: Optional[str]) -> Optional[bool]:
    """An org setting read as a switch: None when not set."""
    if value is None or not value.strip():
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


async def startup_sync_orgs(db: AsyncSession) -> list[int]:
    """The organisations the startup sync may touch: those whose org setting
    machinedb_enabled is on, or, when no organisation says either way, the
    single organisation with plants. MachineDB is one company's press list,
    so a multi-org install never gets it copied into every org by default."""
    orgs = sorted(set((await db.execute(select(Plant.organization_id))).scalars().all()))
    flags = {o: _truthy(await cs.get_setting(db, o, SETTING_MACHINEDB_ENABLED)) for o in orgs}
    on = [o for o in orgs if flags[o]]
    if on:
        return on
    if len(orgs) == 1 and flags[orgs[0]] is not False:
        return orgs
    return []


async def sync_on_startup() -> None:
    """Best effort, in the background: one sync per configured organisation
    (startup_sync_orgs), when MachineDB is configured. Never forced: a broken
    answer is recorded, not applied. Never raises."""
    import os
    if not machinedb_client.is_configured():
        return
    if (os.getenv("MACHINEDB_SYNC_ON_STARTUP") or "1").strip().lower() in ("0", "false", "no"):
        return
    from app.models import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            orgs = await startup_sync_orgs(db)
        if not orgs:
            logger.info("MachineDB startup sync: no organisation has machinedb_enabled")
            return
        machines, skipped = await machinedb_client.list_machines()
    except Exception as e:  # noqa: BLE001 - never block or crash startup
        logger.warning("MachineDB startup sync skipped: %s", e)
        return
    for org_id in orgs:
        try:
            async with AsyncSessionLocal() as db:
                try:
                    res = await sync_machines(db, org_id, None, machines=machines,
                                              skipped=skipped)
                except CostSheetError as e:
                    await db.commit()             # keep the refused attempt on record
                    logger.warning("MachineDB startup sync refused for org %s: %s",
                                   org_id, e.message)
                    continue
                await db.commit()
            logger.info("MachineDB sync org %s: %s machines, %s new, %s changed, "
                        "%s retired, %s unmapped", org_id, res["total"], res["new"],
                        res["changed"], res["retired"], res["unmapped"])
        except Exception as e:  # noqa: BLE001
            logger.warning("MachineDB startup sync failed for org %s: %s", org_id, e)
