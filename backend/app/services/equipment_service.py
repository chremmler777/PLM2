"""Gauges, assembly equipment and EOATs: changing them with a history log.

PLM is the one source for equipment (Christoph, 2026-11-16). An item of category
gauge or assembly_equipment (an EOAT is assembly equipment numbered <tool>-1x) may
serve one tool, several tools or none (an assembly operation, an assembly gauge),
and every change to it lands in the existing log (revision_changelogs) with a kind:

  correction   it was entered wrong
  change       the equipment itself changed (also: links and amounts, logged for the user)
  obsolete     taken out of use; stays in PLM, takes no new links, cannot be edited
  reactivated  back in use

Tools keep their own editing rules (tool_rights, PartService.update_part)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Plant, Project
from app.models.part import Part, RevisionChangelog
from app.services.equipment_numbering import PROJECT_FAMILIES, TOOL_FAMILIES, equipment_number
from app.services.part_service import ChangelogService, compute_next_calibration

EQUIPMENT_CATEGORIES = frozenset({"gauge", "assembly_equipment"})
EDIT_KINDS = ("correction", "change")
#: Links an equipment item owns: logged on the item, blocked while it is obsolete.
EQUIPMENT_RELATIONS = frozenset({"serves", "assembles", "checks"})

KIND_MISSING = "Say whether this is a correction or a change."
NOTE_MISSING = "Write a short note on what changed."
OBSOLETE_NOTE_MISSING = "Write a short note on why this item is obsolete."
OBSOLETE_LOCKED = "This item is obsolete. Reactivate it before changing or linking it."
NOT_EQUIPMENT = "Only gauges and assembly equipment can be marked obsolete."
QUANTITY_INVALID = "The amount must be greater than 0."
QUANTITY_ONLY_ASSEMBLES = "Only links from assembly equipment to an article have an amount."


class EquipmentError(ValueError):
    """A refused equipment change; the text is shown to the user as it is."""


def is_equipment(part) -> bool:
    return part is not None and part.item_category in EQUIPMENT_CATEGORIES


def require_active(*parts) -> None:
    """Obsolete items cannot be edited or linked until reactivated."""
    if any(p is not None and p.obsolete_at is not None for p in parts):
        raise EquipmentError(OBSOLETE_LOCKED)


def check_edit_kind(kind: Optional[str], note: Optional[str]) -> tuple[str, Optional[str]]:
    """The required choice of the edit dialog; a change needs its note."""
    if kind not in EDIT_KINDS:
        raise EquipmentError(KIND_MISSING)
    note = (note or "").strip() or None
    if kind == "change" and note is None:
        raise EquipmentError(NOTE_MISSING)
    return kind, note


def format_quantity(quantity) -> str:
    """2.0 -> '2', 0.5 -> '0.5': amounts as people write them."""
    return f"{float(quantity):.3f}".rstrip("0").rstrip(".")


async def _organization_id(session: AsyncSession, project_id: int) -> Optional[int]:
    return (await session.execute(
        select(Plant.organization_id).join(Project, Project.plant_id == Plant.id)
        .where(Project.id == project_id))).scalar_one_or_none()


def _in_organization(stmt, organization_id: Optional[int]):
    """Numbers are unique per organization, across its projects."""
    if organization_id is None:
        return stmt
    return (stmt.join(Project, Project.id == Part.project_id).join(Plant, Plant.id == Project.plant_id)
            .where(Plant.organization_id == organization_id))


async def number_taken(session: AsyncSession, project_id: int, number: str,
                       exclude_part_id: Optional[int] = None) -> bool:
    """Is this number already used by any item of the organization?"""
    stmt = _in_organization(select(Part.id).where(Part.part_number == number),
                            await _organization_id(session, project_id))
    if exclude_part_id is not None:
        stmt = stmt.where(Part.id != exclude_part_id)
    return (await session.execute(stmt.limit(1))).first() is not None


def number_taken_text(number: str) -> str:
    return f"The number {number} is already in use. Pick another number."


async def next_equipment_number(session: AsyncSession, base: str, family: int, project_id: int) -> Optional[str]:
    """Next free <base>-<family><0..9> looking at every item of the organization, so two
    projects never get the same number. base is a tool number (families 1 to 4) or the
    project code (families 6 and 7, equipment without a tool). None when all ten slots
    of the family are taken."""
    stmt = _in_organization(select(Part.part_number).where(Part.part_number.like(f"{base}-{family}%")),
                            await _organization_id(session, project_id))
    taken = set((await session.execute(stmt)).scalars().all())
    for index in range(10):
        candidate = equipment_number(base, family, index)
        if candidate not in taken:
            return candidate
    return None


async def next_number_for_tool(session: AsyncSession, tool: Part, family: int) -> Optional[str]:
    if family not in TOOL_FAMILIES:
        raise EquipmentError("Unknown number family for a tool. Use 1 (EOAT), 2 (in-cell station), "
                             "3 (secondary station) or 4 (gauge).")
    return await next_equipment_number(session, tool.part_number, family, tool.project_id)


async def next_number_without_tool(session: AsyncSession, project: Project, family: int) -> Optional[str]:
    """<project code>-6x for an assembly operation, -7x for an assembly gauge."""
    if family not in PROJECT_FAMILIES:
        raise EquipmentError("Unknown number family without a tool. Use 6 (assembly equipment or EOAT) "
                             "or 7 (gauge).")
    return await next_equipment_number(session, project.code, family, project.id)


async def log(session: AsyncSession, part: Part, user_id: int, kind: str, action: str, description: str,
              *, field: Optional[str] = None, old: Optional[str] = None, new: Optional[str] = None,
              note: Optional[str] = None) -> RevisionChangelog:
    """One history row of an equipment item, through the one changelog writer."""
    return await ChangelogService.log_action(
        session, part_id=part.id, action=action, action_description=description, performed_by=user_id,
        field_name=field, old_value=old, new_value=new, notes=note, change_kind=kind)


async def last_log_id(session: AsyncSession, part_id: int) -> int:
    return (await session.execute(
        select(RevisionChangelog.id).where(RevisionChangelog.part_id == part_id)
        .order_by(RevisionChangelog.id.desc()).limit(1))).scalar_one_or_none() or 0


async def stamp_since(session: AsyncSession, part_id: int, after_id: int, kind: str, note: Optional[str]) -> None:
    """Field rows PartService.update_part wrote for this edit get the edit's kind and note."""
    await session.execute(
        update(RevisionChangelog)
        .where(RevisionChangelog.part_id == part_id, RevisionChangelog.id > after_id,
               RevisionChangelog.change_kind.is_(None))
        .values(change_kind=kind, notes=note))


async def edit_own_fields(session: AsyncSession, part: Part, user_id: int, kind: str, note: Optional[str], *,
                          part_number: Optional[str] = None, description: Optional[str] = None,
                          update_description: bool = False,
                          calibration_interval_months: Optional[int] = None) -> None:
    """Number, description and calibration interval of an equipment item: one history row
    per field that really changed. (Name and the other shared fields go through
    PartService.update_part, which logs them; the caller stamps those rows.)"""
    async def changed(field: str, label: str, old, new) -> None:
        await log(session, part, user_id, kind, "field_updated",
                  f"{label}: {old if old not in (None, '') else 'none'} -> {new if new not in (None, '') else 'none'}",
                  field=field, old=None if old is None else str(old), new=None if new is None else str(new),
                  note=note)

    if part_number is not None:
        number = part_number.strip()
        if not number:
            raise EquipmentError("The number cannot be empty.")
        if number != part.part_number:
            if await number_taken(session, part.project_id, number, exclude_part_id=part.id):
                raise EquipmentError(number_taken_text(number))
            old, part.part_number = part.part_number, number
            await changed("part_number", "Number", old, number)
    if update_description:
        text = (description or "").strip() or None
        if text != (part.description or None):
            old, part.description = part.description, text
            await changed("description", "Description", old, text)
    if calibration_interval_months is not None and calibration_interval_months != part.calibration_interval_months:
        old, part.calibration_interval_months = part.calibration_interval_months, calibration_interval_months
        part.next_calibration_due = compute_next_calibration(part.last_calibrated_at, calibration_interval_months)
        await changed("calibration_interval_months", "Calibration interval (months)", old, calibration_interval_months)
    part.updated_by = user_id
    part.updated_at = datetime.utcnow()
    await session.flush()


async def mark_obsolete(session: AsyncSession, part: Part, user_id: int, note: Optional[str]) -> Part:
    if not is_equipment(part):
        raise EquipmentError(NOT_EQUIPMENT)
    note = (note or "").strip()
    if not note:
        raise EquipmentError(OBSOLETE_NOTE_MISSING)
    if part.obsolete_at is not None:
        raise EquipmentError("This item is already obsolete.")
    part.obsolete_at = datetime.utcnow()
    part.obsolete_by = user_id
    await log(session, part, user_id, "obsolete", "obsolete", f"Marked obsolete: {note}", note=note)
    return part


async def reactivate(session: AsyncSession, part: Part, user_id: int, note: Optional[str]) -> Part:
    if not is_equipment(part):
        raise EquipmentError(NOT_EQUIPMENT)
    if part.obsolete_at is None:
        raise EquipmentError("This item is not obsolete.")
    note = (note or "").strip() or None
    part.obsolete_at = None
    part.obsolete_by = None
    await log(session, part, user_id, "reactivated", "reactivated",
              f"Reactivated: {note}" if note else "Reactivated", note=note)
    return part


def _named(other: Part) -> str:
    return f"{'Tool' if other.item_category == 'tool' else 'Article' if other.item_category == 'article' else 'Item'} {other.part_number}"


async def log_link_added(session: AsyncSession, equipment: Part, other: Part, user_id: int, quantity) -> None:
    text = f"{_named(other)} added"
    if quantity is not None:
        text += f", quantity {format_quantity(quantity)}"
    await log(session, equipment, user_id, "change", "relation_added", text)


async def log_link_removed(session: AsyncSession, equipment: Part, other: Part, user_id: int) -> None:
    await log(session, equipment, user_id, "change", "relation_removed", f"{_named(other)} removed")


async def log_quantity_changed(session: AsyncSession, equipment: Part, other: Part, user_id: int, old, new) -> None:
    await log(session, equipment, user_id, "change", "quantity_changed",
              f"{_named(other)} quantity {format_quantity(old) if old is not None else 'none'} -> {format_quantity(new)}",
              field="quantity", old=None if old is None else format_quantity(old), new=format_quantity(new))


async def history(session: AsyncSession, part_id: int) -> list[dict]:
    """The item's log, newest first."""
    from sqlalchemy.orm import joinedload
    rows = (await session.execute(
        select(RevisionChangelog).where(RevisionChangelog.part_id == part_id)
        .options(joinedload(RevisionChangelog.performed_by_user))
        .order_by(RevisionChangelog.performed_at.desc(), RevisionChangelog.id.desc()))).scalars().all()
    return [{
        "id": r.id, "at": r.performed_at,
        "by_name": (r.performed_by_user.full_name or r.performed_by_user.username) if r.performed_by_user else None,
        "kind": r.change_kind, "description": r.action_description, "note": r.notes,
        "field": r.field_name, "old_value": r.old_value, "new_value": r.new_value,
    } for r in rows]
