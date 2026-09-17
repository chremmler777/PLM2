"""Form instance lifecycle and SEP item linking."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.forms.compute import recompute
from app.forms.loader import latest_definition
from app.forms.prefill import build_prefill
from app.forms.validate import missing_for_submit, validate_data
from app.models import User, Project
from app.models.forms import FormInstance, FormEvent, FormDefinition
from app.models.sep import SepWorkItem, SepGate, SepItemAudit


class FormError(Exception):
    def __init__(self, status: int, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.status, self.detail, self.extra = status, detail, extra or {}


def sep_refs(body: dict) -> list[tuple[str, int]]:
    out = []
    for ref in body.get("sep_items", []):
        code, _, no = ref.rpartition(":")
        out.append((code, int(no)))
    return out


async def load_instance(db: AsyncSession, instance_id: int) -> FormInstance:
    inst = (await db.execute(
        select(FormInstance)
        .options(selectinload(FormInstance.events), selectinload(FormInstance.definition))
        .where(FormInstance.id == instance_id))).scalar_one_or_none()
    if not inst:
        raise FormError(404, "Form instance not found")
    return inst


async def create_instance(db: AsyncSession, project_id: int, key: str, user: User) -> FormInstance:
    project = await db.get(Project, project_id)
    if not project:
        raise FormError(404, "Project not found")
    definition = await latest_definition(db, key)
    if not definition:
        raise FormError(404, f"Unknown form {key}")
    if definition.cardinality == "single":
        exists = (await db.execute(
            select(FormInstance.id).join(FormDefinition).where(
                FormInstance.project_id == project_id, FormDefinition.key == key).limit(1))).scalar_one_or_none()
        if exists:
            raise FormError(409, f"{definition.title} already exists for this project", {"instance_id": exists})
    data = recompute(definition.body, await build_prefill(db, definition.body, project, user))
    inst = FormInstance(project_id=project_id, definition_id=definition.id, status="draft", data=data,
                        owner_id=user.id, created_by=user.id, updated_by=user.id)
    db.add(inst)
    await db.flush()
    db.add(FormEvent(instance_id=inst.id, user_id=user.id, event="created"))
    await db.flush()
    return await load_instance(db, inst.id)


def _diff(old: dict, new: dict, prefix: str = "") -> dict:
    out = {}
    keys = set(old) | set(new)
    for k in keys:
        if k.endswith("_footer"):
            continue
        a, b = old.get(k), new.get(k)
        path = f"{prefix}{k}"
        if isinstance(a, dict) and isinstance(b, dict):
            out.update(_diff(a, b, path + "."))
        elif a != b:
            out[path] = [a, b]
    return out


async def save_instance(db: AsyncSession, inst: FormInstance, data: dict, user: User,
                        owner_id: int | None = None) -> FormInstance:
    if inst.status == "submitted":
        raise FormError(409, "Form is submitted; reopen it to edit")
    problems = validate_data(inst.definition.body, data)
    if problems:
        raise FormError(422, "Invalid form data", {"problems": problems})
    new = recompute(inst.definition.body, data)
    diff = _diff(inst.data or {}, new)
    if owner_id is not None and owner_id != inst.owner_id:
        diff["owner_id"] = [inst.owner_id, owner_id]
        inst.owner_id = owner_id
    inst.data = new
    inst.updated_by = user.id
    inst.updated_at = datetime.utcnow()
    inst.events.append(FormEvent(user_id=user.id, event="saved", diff=diff))
    await db.flush()
    return await load_instance(db, inst.id)


async def _linked_items(db: AsyncSession, inst: FormInstance) -> list[tuple[SepWorkItem, SepGate]]:
    refs = sep_refs(inst.definition.body)
    if not refs:
        return []
    rows = (await db.execute(
        select(SepWorkItem, SepGate).join(SepGate, SepWorkItem.gate_id == SepGate.id)
        .where(SepWorkItem.project_id == inst.project_id))).all()
    return [(i, g) for i, g in rows if (g.code, i.item_no) in refs]


def _audit(item: SepWorkItem, user_id: int, old: str, new: str) -> SepItemAudit:
    return SepItemAudit(item_id=item.id, user_id=user_id, field="status", old_value=old, new_value=new)


async def submit_instance(db: AsyncSession, inst: FormInstance, user: User) -> FormInstance:
    if inst.status == "submitted":
        raise FormError(409, "Form already submitted")
    missing = missing_for_submit(inst.definition.body, inst.data or {})
    if missing:
        raise FormError(422, "Form is incomplete", {"missing": missing})
    title = inst.definition.title
    flipped: list[int] = []
    for item, gate in await _linked_items(db, inst):
        if gate.status == "closed" or item.status != "open":
            continue
        db.add(_audit(item, user.id, "open", "done"))
        item.status = "done"
        item.completed_at = datetime.utcnow()
        if not item.remark:
            item.remark = f"via form {title}"
        flipped.append(item.id)
    inst.status = "submitted"
    inst.submitted_by = user.id
    inst.submitted_at = datetime.utcnow()
    inst.events.append(FormEvent(user_id=user.id, event="submitted", diff={"items": flipped}))
    await db.flush()
    return await load_instance(db, inst.id)


def _last_submitted_items(inst: FormInstance) -> set[int]:
    """Ids of the SEP items the most recent submission of this instance flipped to done."""
    for e in reversed(inst.events):
        if e.event == "submitted":
            return {int(i) for i in (e.diff or {}).get("items") or []}
    return set()


async def reopen_instance(db: AsyncSession, inst: FormInstance, user: User) -> FormInstance:
    if inst.status != "submitted":
        raise FormError(409, "Only submitted forms can be reopened")
    flipped = _last_submitted_items(inst)
    for item, gate in await _linked_items(db, inst):
        if item.id not in flipped or gate.status == "closed" or item.status != "done":
            continue
        db.add(_audit(item, user.id, "done", "open"))
        item.status = "open"
        item.completed_at = None
    inst.status = "reopened"
    inst.events.append(FormEvent(user_id=user.id, event="reopened"))
    await db.flush()
    return await load_instance(db, inst.id)


def _events_since_submit(inst: FormInstance) -> list[FormEvent]:
    idx = 0
    for i, e in enumerate(inst.events):
        if e.event in ("submitted", "reopened"):
            idx = i
    return inst.events[idx:]


def signatures_state(inst: FormInstance) -> dict:
    roles = inst.definition.body.get("signatures", [])
    state = {r: None for r in roles}
    if inst.status != "submitted":
        return state
    for e in _events_since_submit(inst):
        if e.event == "signed" and e.role in state:
            state[e.role] = {"user_id": e.user_id, "at": e.created_at.isoformat()}
    return state


async def sign_instance(db: AsyncSession, inst: FormInstance, role: str, user: User) -> FormInstance:
    roles = inst.definition.body.get("signatures", [])
    if role not in roles:
        raise FormError(400, f"Role must be one of: {', '.join(roles) or 'none'}")
    if inst.status != "submitted":
        raise FormError(409, "Form must be submitted before signing")
    state = signatures_state(inst)
    if state[role]:
        raise FormError(409, f"{role.upper()} has already signed")
    if any(s and s["user_id"] == user.id for s in state.values()):
        raise FormError(409, "Each role must be signed by a different user")
    inst.events.append(FormEvent(user_id=user.id, event="signed", role=role))
    await db.flush()
    return await load_instance(db, inst.id)


async def instances_for_project(db: AsyncSession, project_id: int) -> list[FormInstance]:
    return list((await db.execute(
        select(FormInstance).options(selectinload(FormInstance.definition), selectinload(FormInstance.events))
        .where(FormInstance.project_id == project_id).order_by(FormInstance.id))).scalars().all())


async def form_info_by_ref(db: AsyncSession, project_id: int) -> dict[str, dict]:
    """'K0/RG1:2' -> {key, title, instance_id, status} using the latest definition per key
    and the newest instance per key (single forms have at most one)."""
    from app.forms.loader import latest_definitions
    latest = await latest_definitions(db)
    insts = await instances_for_project(db, project_id)
    newest: dict[str, FormInstance] = {}
    for i in insts:
        newest[i.definition.key] = i
    out: dict[str, dict] = {}
    for d in latest:
        inst = newest.get(d.key)
        for ref in d.body.get("sep_items", []):
            out[ref] = {"key": d.key, "title": d.title,
                        "instance_id": inst.id if inst else None,
                        "status": inst.status if inst else None}
    return out
