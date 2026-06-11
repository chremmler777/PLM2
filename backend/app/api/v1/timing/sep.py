"""SEP Q-Gate endpoints - strict stage-gate process per GB-DP-0001 SEP matrix.

Lifecycle: activate copies the seeded template (7 gates, 232 work items) into
project-owned rows; gate 1 opens. Work items are tri-state (open/done/
not_applicable) and audited. A gate closes via dual sign-off (PM + Quality,
different users) and only when the previous gate is closed; a yellow gate
(open items) additionally requires risk entries with complete action plans
(countermeasure, responsible, due date within 14 days). Closing locks items
and opens the next gate.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user
from app.models import get_db, User, Project, ProjectMilestone
from app.models.sep import (
    SepGate, SepWorkItem, SepItemAudit, SepRisk,
    SEP_ITEM_STATUSES, SEP_RISK_STATUSES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sep", tags=["sep"])

TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "data" / "sep_template.json"
ACTION_PLAN_MAX_DAYS = 14
SIGN_OFF_ROLES = {"pm", "quality"}


class ItemUpdate(BaseModel):
    status: Optional[str] = None
    remark: Optional[str] = None
    responsible_id: Optional[int] = None
    clear_responsible: bool = False


class GateUpdate(BaseModel):
    target_date: Optional[datetime] = None
    milestone_id: Optional[int] = None
    clear_milestone: bool = False


class SignOffRequest(BaseModel):
    role: str  # "pm" | "quality"


class RiskCreate(BaseModel):
    effect: str = Field(min_length=3)
    q_impact: float = Field(0.0, ge=0, le=1)
    c_impact: float = Field(0.0, ge=0, le=1)
    s_impact: float = Field(0.0, ge=0, le=1)
    probability: float = Field(0.0, ge=0, le=1)
    countermeasure: Optional[str] = None
    due_date: Optional[datetime] = None
    responsible_id: Optional[int] = None


class RiskUpdate(BaseModel):
    effect: Optional[str] = None
    q_impact: Optional[float] = Field(None, ge=0, le=1)
    c_impact: Optional[float] = Field(None, ge=0, le=1)
    s_impact: Optional[float] = Field(None, ge=0, le=1)
    probability: Optional[float] = Field(None, ge=0, le=1)
    countermeasure: Optional[str] = None
    due_date: Optional[datetime] = None
    responsible_id: Optional[int] = None
    status: Optional[str] = None


# ---------------------------------------------------------------- helpers

def _is_lessons_item(item: SepWorkItem) -> bool:
    return "lessons learned" in item.title_en.lower()


def _gate_progress(items: list[SepWorkItem]) -> dict:
    done = sum(1 for i in items if i.status == "done")
    na = sum(1 for i in items if i.status == "not_applicable")
    open_ = sum(1 for i in items if i.status == "open")
    applicable = len(items) - na
    pct = round(100 * done / applicable, 1) if applicable else 100.0
    return {"done": done, "open": open_, "not_applicable": na, "total": len(items), "pct": pct}


def _gate_color(gate: SepGate) -> str:
    """GREEN = no open items; YELLOW = open items; RED = high/very-high risk live."""
    if gate.status == "closed":
        return "green"
    if any(r.status != "finished" and r.priority in ("high", "very_high") for r in gate.risks):
        return "red"
    if any(i.status == "open" for i in gate.items):
        return "yellow"
    return "green"


def _risk_dict(r: SepRisk, names: dict[int, str]) -> dict:
    return {
        "id": r.id,
        "gate_id": r.gate_id,
        "effect": r.effect,
        "q_impact": r.q_impact,
        "c_impact": r.c_impact,
        "s_impact": r.s_impact,
        "probability": r.probability,
        "rkz": r.rkz,
        "priority": r.priority,
        "countermeasure": r.countermeasure,
        "due_date": r.due_date.isoformat() if r.due_date else None,
        "responsible_id": r.responsible_id,
        "responsible_name": names.get(r.responsible_id),
        "status": r.status,
    }


def _item_dict(i: SepWorkItem, names: dict[int, str]) -> dict:
    return {
        "id": i.id,
        "gate_id": i.gate_id,
        "item_no": i.item_no,
        "title_de": i.title_de,
        "title_en": i.title_en,
        "psp_no": i.psp_no,
        "department": i.department,
        "status": i.status,
        "remark": i.remark,
        "responsible_id": i.responsible_id,
        "responsible_name": names.get(i.responsible_id),
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        "lessons_link": _is_lessons_item(i),
    }


def _gate_dict(g: SepGate, names: dict[int, str], with_details: bool = True) -> dict:
    d = {
        "id": g.id,
        "project_id": g.project_id,
        "code": g.code,
        "seq": g.seq,
        "phase_de": g.phase_de,
        "phase_en": g.phase_en,
        "status": g.status,
        "color": _gate_color(g),
        "target_date": g.target_date.isoformat() if g.target_date else None,
        "milestone_id": g.milestone_id,
        "pm_signed_by": g.pm_signed_by,
        "pm_signed_name": names.get(g.pm_signed_by),
        "pm_signed_at": g.pm_signed_at.isoformat() if g.pm_signed_at else None,
        "quality_signed_by": g.quality_signed_by,
        "quality_signed_name": names.get(g.quality_signed_by),
        "quality_signed_at": g.quality_signed_at.isoformat() if g.quality_signed_at else None,
        "closed_at": g.closed_at.isoformat() if g.closed_at else None,
        "progress": _gate_progress(g.items),
        "open_risks": sum(1 for r in g.risks if r.status != "finished"),
    }
    if with_details:
        d["items"] = [_item_dict(i, names) for i in g.items]
        d["risks"] = [_risk_dict(r, names) for r in g.risks]
    return d


async def _user_names(db: AsyncSession, user_ids: set[int | None]) -> dict[int, str]:
    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(ids)))
    return {u.id: u.full_name or u.username for u in result.scalars()}


async def _load_gates(db: AsyncSession, project_id: int) -> list[SepGate]:
    result = await db.execute(
        select(SepGate)
        .where(SepGate.project_id == project_id)
        .options(selectinload(SepGate.items), selectinload(SepGate.risks))
        .order_by(SepGate.seq)
    )
    return list(result.scalars())


async def _load_gate(db: AsyncSession, gate_id: int) -> SepGate:
    result = await db.execute(
        select(SepGate)
        .where(SepGate.id == gate_id)
        .options(selectinload(SepGate.items), selectinload(SepGate.risks))
    )
    gate = result.scalar_one_or_none()
    if not gate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEP gate not found")
    return gate


def _names_in_gates(gates: list[SepGate]) -> set[int | None]:
    ids: set[int | None] = set()
    for g in gates:
        ids.update((g.pm_signed_by, g.quality_signed_by))
        ids.update(i.responsible_id for i in g.items)
        ids.update(r.responsible_id for r in g.risks)
    return ids


def _audit(item: SepWorkItem, user_id: int, field: str, old, new) -> SepItemAudit:
    return SepItemAudit(
        item_id=item.id, user_id=user_id, field=field,
        old_value=str(old) if old is not None else None,
        new_value=str(new) if new is not None else None,
    )


# ---------------------------------------------------------------- endpoints

@router.post("/projects/{project_id}/activate", response_model=dict, status_code=status.HTTP_201_CREATED)
async def activate_sep(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Copy the SEP template into project-owned gates and work items; open gate 1."""
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    existing = (await db.execute(
        select(func.count()).select_from(SepGate).where(SepGate.project_id == project_id)
    )).scalar()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SEP already activated for this project")

    template = json.loads(TEMPLATE_PATH.read_text())
    for tg in template["gates"]:
        gate = SepGate(
            project_id=project_id,
            code=tg["code"],
            seq=tg["seq"],
            phase_de=tg["phase_de"],
            phase_en=tg["phase_en"],
            status="in_progress" if tg["seq"] == 1 else "pending",
        )
        db.add(gate)
        await db.flush()
        for ti in tg["items"]:
            db.add(SepWorkItem(
                gate_id=gate.id,
                project_id=project_id,
                item_no=ti["item_no"],
                title_de=ti["title_de"],
                title_en=ti["title_en"],
                psp_no=ti.get("psp_no"),
                department=ti["department"],
            ))
    await db.commit()

    gates = await _load_gates(db, project_id)
    logger.info("SEP activated for project %s by user %s", project_id, current_user.id)
    return {"project_id": project_id, "gates": [_gate_dict(g, {}, with_details=False) for g in gates]}


@router.get("/projects/{project_id}", response_model=dict)
async def get_project_sep(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full SEP state for a project: gates with items, risks, progress, colors."""
    gates = await _load_gates(db, project_id)
    if not gates:
        return {"project_id": project_id, "active": False, "gates": []}
    names = await _user_names(db, _names_in_gates(gates))
    total_items = [i for g in gates for i in g.items]
    return {
        "project_id": project_id,
        "active": True,
        "gates": [_gate_dict(g, names) for g in gates],
        "rollup": {"total": _gate_progress(total_items)},
    }


@router.get("/projects/{project_id}/rollup", response_model=dict)
async def get_rollup(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """R-grade rollup per gate + total (like the 'Ges. R-Grad' sheet)."""
    gates = await _load_gates(db, project_id)
    if not gates:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEP not activated for this project")
    total_items = [i for g in gates for i in g.items]
    return {
        "project_id": project_id,
        "gates": [_gate_dict(g, {}, with_details=False) for g in gates],
        "total": _gate_progress(total_items),
    }


@router.get("/overview", response_model=list[dict])
async def sep_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard widget: gate colors + progress for every project with SEP."""
    result = await db.execute(
        select(SepGate)
        .options(selectinload(SepGate.items), selectinload(SepGate.risks))
        .order_by(SepGate.project_id, SepGate.seq)
    )
    gates = list(result.scalars())
    if not gates:
        return []
    project_ids = {g.project_id for g in gates}
    projects = (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars()
    project_names = {p.id: p.name for p in projects}

    out: dict[int, dict] = {}
    for g in gates:
        entry = out.setdefault(g.project_id, {
            "project_id": g.project_id,
            "project_name": project_names.get(g.project_id),
            "gates": [],
            "_items": [],
        })
        entry["gates"].append({
            "id": g.id, "code": g.code, "seq": g.seq, "status": g.status,
            "color": _gate_color(g), "pct": _gate_progress(g.items)["pct"],
        })
        entry["_items"].extend(g.items)
    for entry in out.values():
        entry["total"] = _gate_progress(entry.pop("_items"))
        current = next((g for g in entry["gates"] if g["status"] == "in_progress"), None)
        entry["current_gate"] = current["code"] if current else None
    return list(out.values())


@router.get("/my-items", response_model=list[dict])
async def my_items(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Open SEP work items assigned to me, with project and gate context."""
    result = await db.execute(
        select(SepWorkItem, SepGate, Project)
        .join(SepGate, SepWorkItem.gate_id == SepGate.id)
        .join(Project, SepWorkItem.project_id == Project.id)
        .where(
            SepWorkItem.responsible_id == current_user.id,
            SepWorkItem.status == "open",
            SepGate.status != "closed",
        )
        .order_by(SepGate.seq, SepWorkItem.item_no)
    )
    rows = result.all()
    return [
        {
            **_item_dict(item, {}),
            "project_id": project.id,
            "project_name": project.name,
            "gate_code": gate.code,
            "gate_status": gate.status,
            "gate_target_date": gate.target_date.isoformat() if gate.target_date else None,
        }
        for item, gate, project in rows
    ]


@router.patch("/items/{item_id}", response_model=dict)
async def update_item(
    item_id: int,
    body: ItemUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a work item (tri-state status, remark, responsible). Audited."""
    item = (await db.execute(select(SepWorkItem).where(SepWorkItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
    gate = (await db.execute(select(SepGate).where(SepGate.id == item.gate_id))).scalar_one()
    if gate.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gate is closed; items are locked")

    if body.status is not None and body.status != item.status:
        if body.status not in SEP_ITEM_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Invalid status; allowed: {', '.join(SEP_ITEM_STATUSES)}")
        db.add(_audit(item, current_user.id, "status", item.status, body.status))
        item.status = body.status
        item.completed_at = datetime.utcnow() if body.status == "done" else None

    if body.remark is not None and body.remark != item.remark:
        db.add(_audit(item, current_user.id, "remark", item.remark, body.remark))
        item.remark = body.remark

    if body.clear_responsible and item.responsible_id is not None:
        db.add(_audit(item, current_user.id, "responsible_id", item.responsible_id, None))
        item.responsible_id = None
    elif body.responsible_id is not None and body.responsible_id != item.responsible_id:
        user = (await db.execute(select(User).where(User.id == body.responsible_id))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Responsible user not found")
        db.add(_audit(item, current_user.id, "responsible_id", item.responsible_id, body.responsible_id))
        item.responsible_id = body.responsible_id

    await db.commit()
    await db.refresh(item)
    names = await _user_names(db, {item.responsible_id})
    return _item_dict(item, names)


@router.get("/items/{item_id}/audits", response_model=list[dict])
async def item_audits(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SepItemAudit).where(SepItemAudit.item_id == item_id).order_by(SepItemAudit.created_at.desc())
    )
    audits = list(result.scalars())
    names = await _user_names(db, {a.user_id for a in audits})
    return [
        {
            "id": a.id, "field": a.field, "old_value": a.old_value, "new_value": a.new_value,
            "user_id": a.user_id, "user_name": names.get(a.user_id),
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in audits
    ]


@router.patch("/gates/{gate_id}", response_model=dict)
async def update_gate(
    gate_id: int,
    body: GateUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set gate target date or link it to a project milestone."""
    gate = await _load_gate(db, gate_id)
    if gate.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gate is closed")

    if body.target_date is not None:
        gate.target_date = body.target_date
    if body.clear_milestone:
        gate.milestone_id = None
    elif body.milestone_id is not None:
        milestone = (await db.execute(
            select(ProjectMilestone).where(ProjectMilestone.id == body.milestone_id)
        )).scalar_one_or_none()
        if not milestone or milestone.project_id != gate.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Milestone not found in this project")
        gate.milestone_id = body.milestone_id
        if gate.target_date is None:
            gate.target_date = milestone.due_date
    await db.commit()
    gate = await _load_gate(db, gate_id)
    names = await _user_names(db, _names_in_gates([gate]))
    return _gate_dict(gate, names)


@router.post("/gates/{gate_id}/sign-off", response_model=dict)
async def sign_off_gate(
    gate_id: int,
    body: SignOffRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sign a gate as PM or Quality. Both signatures (different users) close it.

    Gates close strictly in sequence. A gate with open items (yellow) needs at
    least one risk entry, and every unfinished risk a complete action plan:
    countermeasure, responsible, due date within 14 days.
    """
    gate = await _load_gate(db, gate_id)
    role = body.role.lower().strip()
    if role not in SIGN_OFF_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role must be 'pm' or 'quality'")
    if gate.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gate already closed")
    if gate.status == "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Gate not yet open; previous gate must be closed first")

    if gate.seq > 1:
        prev = (await db.execute(select(SepGate).where(
            SepGate.project_id == gate.project_id, SepGate.seq == gate.seq - 1
        ))).scalar_one()
        if prev.status != "closed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"Previous gate {prev.code} must be closed first")

    open_items = [i for i in gate.items if i.status == "open"]
    unfinished_risks = [r for r in gate.risks if r.status != "finished"]
    if open_items:
        if not gate.risks:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{len(open_items)} open work items: a risk assessment with action plan is required (yellow gate)",
            )
    deadline = datetime.utcnow() + timedelta(days=ACTION_PLAN_MAX_DAYS)
    if open_items or unfinished_risks:
        incomplete = [
            r.id for r in unfinished_risks
            if not (r.countermeasure and r.countermeasure.strip()) or not r.due_date or not r.responsible_id
        ]
        if incomplete:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Risk entries {incomplete} need countermeasure, responsible and due date before sign-off",
            )
        overdue = [r.id for r in unfinished_risks if r.due_date > deadline]
        if overdue:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Risk entries {overdue}: action plan due date must be within {ACTION_PLAN_MAX_DAYS} days",
            )

    now = datetime.utcnow()
    if role == "pm":
        if gate.pm_signed_by:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="PM has already signed this gate")
        if gate.quality_signed_by == current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="PM and Quality sign-off must be different users")
        gate.pm_signed_by = current_user.id
        gate.pm_signed_at = now
    else:
        if gate.quality_signed_by:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quality has already signed this gate")
        if gate.pm_signed_by == current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="PM and Quality sign-off must be different users")
        gate.quality_signed_by = current_user.id
        gate.quality_signed_at = now

    if gate.pm_signed_by and gate.quality_signed_by:
        gate.status = "closed"
        gate.closed_at = now
        next_gate = (await db.execute(select(SepGate).where(
            SepGate.project_id == gate.project_id, SepGate.seq == gate.seq + 1
        ))).scalar_one_or_none()
        if next_gate and next_gate.status == "pending":
            next_gate.status = "in_progress"
        logger.info("SEP gate %s (project %s) closed by dual sign-off", gate.code, gate.project_id)

    await db.commit()
    gate = await _load_gate(db, gate_id)
    names = await _user_names(db, _names_in_gates([gate]))
    return _gate_dict(gate, names)


@router.post("/gates/{gate_id}/risks", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_risk(
    gate_id: int,
    body: RiskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gate = await _load_gate(db, gate_id)
    if gate.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gate is closed")
    risk = SepRisk(
        gate_id=gate.id,
        project_id=gate.project_id,
        effect=body.effect,
        q_impact=body.q_impact,
        c_impact=body.c_impact,
        s_impact=body.s_impact,
        probability=body.probability,
        countermeasure=body.countermeasure,
        due_date=body.due_date,
        responsible_id=body.responsible_id,
        created_by=current_user.id,
    )
    db.add(risk)
    await db.commit()
    await db.refresh(risk)
    names = await _user_names(db, {risk.responsible_id})
    return _risk_dict(risk, names)


@router.patch("/risks/{risk_id}", response_model=dict)
async def update_risk(
    risk_id: int,
    body: RiskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    risk = (await db.execute(select(SepRisk).where(SepRisk.id == risk_id))).scalar_one_or_none()
    if not risk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    gate = (await db.execute(select(SepGate).where(SepGate.id == risk.gate_id))).scalar_one()
    if gate.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gate is closed")
    if body.status is not None and body.status not in SEP_RISK_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Invalid status; allowed: {', '.join(SEP_RISK_STATUSES)}")
    for field in ("effect", "q_impact", "c_impact", "s_impact", "probability",
                  "countermeasure", "due_date", "responsible_id", "status"):
        value = getattr(body, field)
        if value is not None:
            setattr(risk, field, value)
    await db.commit()
    await db.refresh(risk)
    names = await _user_names(db, {risk.responsible_id})
    return _risk_dict(risk, names)


@router.delete("/risks/{risk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_risk(
    risk_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    risk = (await db.execute(select(SepRisk).where(SepRisk.id == risk_id))).scalar_one_or_none()
    if not risk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    gate = (await db.execute(select(SepGate).where(SepGate.id == risk.gate_id))).scalar_one()
    if gate.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gate is closed")
    await db.delete(risk)
    await db.commit()


# -------------------------------------------------- lessons-module hook

async def mark_lessons_items_done(db: AsyncSession, project_id: int, user_id: int, lesson_id: int) -> int:
    """Called when a lesson reuse is recorded for a project: complete open
    'Lessons learned' work items in the project's current in-progress gate.
    Returns the number of items marked done. Caller commits."""
    result = await db.execute(
        select(SepWorkItem)
        .join(SepGate, SepWorkItem.gate_id == SepGate.id)
        .where(
            SepWorkItem.project_id == project_id,
            SepWorkItem.status == "open",
            SepGate.status == "in_progress",
        )
    )
    count = 0
    for item in result.scalars():
        if not _is_lessons_item(item):
            continue
        db.add(_audit(item, user_id, "status", item.status, "done"))
        item.status = "done"
        item.completed_at = datetime.utcnow()
        item.remark = ((item.remark + " | ") if item.remark else "") + f"Lesson reuse recorded (lesson #{lesson_id})"
        count += 1
    return count
