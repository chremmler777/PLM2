"""The worksheet audit log: the part changelog (revision_changelogs) of a
project's parts, limited to the actions that change or annotate a worksheet
cell. No table of its own: field notes, material, article and tool value
changes, paint and DFM events are logged there already, including what the
1994 import scripts wrote.

AUDIT_ACTIONS is the one allow-list. An action either carries the worksheet
field key in field_name (field notes, material), maps a legacy field_name
through FIELD_NAME_KEYS (metadata and value updates; unmapped names are not
worksheet fields and stay out), or has a fixed key (paint, DFM)."""
import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import User
from app.models.part import Part, RevisionChangelog

AUDIT_GROUPS = ("comments", "flags", "material", "values", "other")

# How an action names its field: "key" (field_name is the worksheet key),
# "mapped" (field_name through FIELD_NAME_KEYS) or a fixed worksheet key.
KEY = "key"
MAPPED = "mapped"


@dataclass(frozen=True)
class AuditAction:
    group: str
    field: str


AUDIT_ACTIONS: dict[str, AuditAction] = {
    "field_comment_added": AuditAction("comments", KEY),
    "field_flag_set": AuditAction("flags", KEY),
    "material_set": AuditAction("material", KEY),
    "material_refreshed": AuditAction("material", KEY),
    "metadata_updated": AuditAction("values", MAPPED),
    "field_updated": AuditAction("values", MAPPED),
    "renumbered": AuditAction("values", MAPPED),
    "lifecycle_phase": AuditAction("values", MAPPED),
    "paint_updated": AuditAction("values", "paint.colour"),
    "dfm_topic_opened": AuditAction("other", "dfm.status"),
    "dfm_topic_closed": AuditAction("other", "dfm.status"),
    "dfm_topic_reopened": AuditAction("other", "dfm.status"),
    "dfm_entry_recorded": AuditAction("other", "dfm.status"),
}

# Changelog field_name -> worksheet field key (worksheetColumns.ts / field note keys).
FIELD_NAME_KEYS: dict[str, str] = {
    "part_number": "part.part_number",
    "customer_part_number": "part.customer_part_number",
    "tier1_part_number": "part.tier1_part_number",
    "name": "part.name",
    "part_type": "part.part_type",
    "mirror_of": "part.mirror_of",
    "lifecycle_phase": "part.lifecycle_phase",
    "colour_code": "part.colour_code",
    "grain": "part.grain",
    "customer_index": "revision.level",
    "customer_received_at": "revision.level",
    "tool_cavities": "tool.cavities",
    "tool_cycle_time_s": "tool.cycle_time_s",
    "tool_tonnage_class": "tool.tonnage_class",
    "toolmaker_id": "tool.toolmaker",
}

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_CSV_ROWS = 10_000


def audit_field_key(action: str, field_name: Optional[str]) -> Optional[str]:
    spec = AUDIT_ACTIONS.get(action)
    if spec is None:
        return None
    if spec.field == KEY:
        return field_name
    if spec.field == MAPPED:
        return FIELD_NAME_KEYS.get(field_name or "")
    return spec.field


def _actions(kind: str) -> list[str]:
    """Actions whose field is named by kind: KEY, MAPPED, or any fixed key ("fixed")."""
    if kind in (KEY, MAPPED):
        return [a for a, s in AUDIT_ACTIONS.items() if s.field == kind]
    return [a for a, s in AUDIT_ACTIONS.items() if s.field not in (KEY, MAPPED)]


def _allowed():
    """Allow-listed actions; mapped ones only for field names that are worksheet fields."""
    C = RevisionChangelog
    return or_(C.action.in_(_actions(KEY)), C.action.in_(_actions("fixed")),
               and_(C.action.in_(_actions(MAPPED)), C.field_name.in_(list(FIELD_NAME_KEYS))))


def _field_filter(field_key: str):
    C = RevisionChangelog
    names = [n for n, k in FIELD_NAME_KEYS.items() if k == field_key]
    fixed = [a for a, s in AUDIT_ACTIONS.items() if s.field == field_key]
    conds = [and_(C.action.in_(_actions(KEY)), C.field_name == field_key)]
    if names:
        conds.append(and_(C.action.in_(_actions(MAPPED)), C.field_name.in_(names)))
    if fixed:
        conds.append(C.action.in_(fixed))
    return or_(*conds)


async def audit_entries(db: AsyncSession, project_id: int, *, action_group: Optional[str] = None,
                        part_id: Optional[int] = None, part: Optional[str] = None,
                        field_key: Optional[str] = None, before_id: Optional[int] = None,
                        limit: int = DEFAULT_LIMIT) -> tuple[list[dict], bool]:
    """Newest first. Returns (entries, has_more)."""
    C = RevisionChangelog
    q = (select(C, Part, User)
         .join(Part, Part.id == C.part_id)
         .outerjoin(User, User.id == C.performed_by)
         .where(Part.project_id == project_id, _allowed()))
    if action_group:
        q = q.where(C.action.in_([a for a, s in AUDIT_ACTIONS.items() if s.group == action_group]))
    if part_id is not None:
        q = q.where(C.part_id == part_id)
    if part:
        like = f"%{part.strip()}%"
        q = q.where(or_(Part.part_number.ilike(like), Part.customer_part_number.ilike(like)))
    if field_key:
        q = q.where(_field_filter(field_key))
    if before_id is not None:
        q = q.where(C.id < before_id)
    rows = (await db.execute(q.order_by(C.id.desc()).limit(limit + 1))).all()
    entries = [_entry(c, p, u) for c, p, u in rows[:limit]]
    return entries, len(rows) > limit


def _iso(at: Optional[datetime]) -> Optional[str]:
    return at.isoformat() if at else None


def _entry(c: RevisionChangelog, p: Part, u: Optional[User]) -> dict:
    spec = AUDIT_ACTIONS[c.action]
    return {
        "id": c.id,
        "at": _iso(c.performed_at),
        "actor": {"id": u.id, "name": u.full_name or u.username} if u else None,
        "part": {"id": p.id, "part_number": p.part_number, "customer_part_number": p.customer_part_number,
                 "item_category": p.item_category},
        "action": c.action,
        "action_group": spec.group,
        "field_key": audit_field_key(c.action, c.field_name),
        "old_value": c.old_value,
        "new_value": c.new_value,
        "description": c.action_description,
    }


CSV_HEADER = ["Time (UTC)", "User", "KTX no.", "OEM no.", "Group", "Action", "Field", "Old value", "New value",
              "Description"]


def _cell(value) -> str:
    """Text a spreadsheet would run as a formula is kept as text."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def build_csv(entries: list[dict]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_HEADER)
    for e in entries:
        w.writerow([_cell(v) for v in (
            (e["at"] or "")[:19].replace("T", " "), (e["actor"] or {}).get("name"), e["part"]["part_number"],
            e["part"]["customer_part_number"], e["action_group"], e["action"], e["field_key"], e["old_value"],
            e["new_value"], e["description"])])
    return ("﻿" + out.getvalue()).encode("utf-8")
