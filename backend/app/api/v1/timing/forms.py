"""SEP forms engine endpoints (/v1/forms)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User, Project
from app.forms.loader import latest_definitions, latest_definition
from app.forms import service as svc
from app.forms.service import FormError

router = APIRouter(prefix="/forms", tags=["forms"])


class CreateBody(BaseModel):
    key: str


class SaveBody(BaseModel):
    data: dict
    owner_id: Optional[int] = None


class SignBody(BaseModel):
    role: str


def _raise(e: FormError) -> None:
    detail = {"message": e.detail, **e.extra} if e.extra else e.detail
    raise HTTPException(status_code=e.status, detail=detail)


async def _names(db: AsyncSession, ids: set[int | None]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    return {i: n for i, n in rows}


def _def_dict(d) -> dict:
    return {"key": d.key, "version": d.version, "title": d.title, "implements": d.implements,
            "cardinality": d.cardinality, "gate_items": d.gate_items,
            "sep_items": d.body.get("sep_items", []), "signatures": d.body.get("signatures", [])}


async def _inst_dict(db: AsyncSession, inst, full: bool = False, names: dict[int, str] | None = None) -> dict:
    d = inst.definition
    sigs = svc.signatures_state(inst)
    if names is None:
        names = await _names(db, {inst.owner_id, inst.submitted_by, inst.updated_by}
                             | {s["user_id"] for s in sigs.values() if s} | {e.user_id for e in inst.events})
    out = {
        "id": inst.id, "project_id": inst.project_id, "key": d.key, "title": d.title, "version": d.version,
        "implements": d.implements, "cardinality": d.cardinality, "status": inst.status, "data": inst.data,
        "owner_id": inst.owner_id, "owner_name": names.get(inst.owner_id),
        "created_by": inst.created_by, "created_at": inst.created_at.isoformat(),
        "updated_by": inst.updated_by, "updated_by_name": names.get(inst.updated_by), "updated_at": inst.updated_at.isoformat(),
        "submitted_by": inst.submitted_by, "submitted_by_name": names.get(inst.submitted_by),
        "submitted_at": inst.submitted_at.isoformat() if inst.submitted_at else None,
        "signatures": {r: ({**s, "user_name": names.get(s["user_id"])} if s else None) for r, s in sigs.items()},
        "references": d.body.get("references", []), "sep_items": d.body.get("sep_items", []),
    }
    if full:
        out["definition"] = d.body
        out["events"] = [{"id": e.id, "user_id": e.user_id, "user_name": names.get(e.user_id), "event": e.event,
                          "role": e.role, "diff": e.diff, "created_at": e.created_at.isoformat()} for e in inst.events]
    return out


@router.get("/definitions", response_model=list[dict])
async def list_definitions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [_def_dict(d) for d in await latest_definitions(db)]


@router.get("/definitions/{key}", response_model=dict)
async def get_definition(key: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = await latest_definition(db, key)
    if not d:
        raise HTTPException(status_code=404, detail="Unknown form")
    return {**_def_dict(d), "body": d.body}


@router.get("/projects/{project_id}", response_model=list[dict])
async def project_forms(project_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    insts = await svc.instances_for_project(db, project_id)
    ids: set[int | None] = set()
    for i in insts:
        ids |= {i.owner_id, i.submitted_by, i.updated_by}
        ids |= {s["user_id"] for s in svc.signatures_state(i).values() if s}
        ids |= {e.user_id for e in i.events}
    names = await _names(db, ids)
    groups = []
    for d in await latest_definitions(db):
        mine = [await _inst_dict(db, i, names=names) for i in insts if i.definition.key == d.key]
        groups.append({**_def_dict(d), "instances": mine})
    return groups


@router.post("/projects/{project_id}/instances", response_model=dict, status_code=201)
async def create_instance(project_id: int, body: CreateBody,
                          current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        inst = await svc.create_instance(db, project_id, body.key, current_user)
    except FormError as e:
        _raise(e)
    await db.commit()
    return await _inst_dict(db, await svc.load_instance(db, inst.id), full=True)


@router.get("/instances/{instance_id}", response_model=dict)
async def get_instance(instance_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        inst = await svc.load_instance(db, instance_id)
    except FormError as e:
        _raise(e)
    return await _inst_dict(db, inst, full=True)


async def _mutate(db, instance_id, fn, *args):
    try:
        inst = await svc.load_instance(db, instance_id)
        inst = await fn(db, inst, *args)
    except FormError as e:
        _raise(e)
    await db.commit()
    return await _inst_dict(db, await svc.load_instance(db, inst.id), full=True)


@router.patch("/instances/{instance_id}", response_model=dict)
async def save_instance(instance_id: int, body: SaveBody,
                        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _mutate(db, instance_id, lambda d, i, data, user: svc.save_instance(d, i, data, user, body.owner_id),
                         body.data, current_user)


@router.post("/instances/{instance_id}/submit", response_model=dict)
async def submit(instance_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _mutate(db, instance_id, svc.submit_instance, current_user)


@router.post("/instances/{instance_id}/reopen", response_model=dict)
async def reopen(instance_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _mutate(db, instance_id, svc.reopen_instance, current_user)


@router.post("/instances/{instance_id}/sign", response_model=dict)
async def sign(instance_id: int, body: SignBody,
               current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _mutate(db, instance_id, lambda d, i, user: svc.sign_instance(d, i, body.role.lower().strip(), user),
                         current_user)


@router.get("/my-forms", response_model=list[dict])
async def my_forms(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Forms I own that are not yet submitted (draft/reopened). There is no role model, so we
    cannot tell who a missing signature belongs to; without that, submitted-but-unsigned forms
    can't be attributed to a specific user and are intentionally left out of this list."""
    from sqlalchemy.orm import selectinload
    from app.models.forms import FormInstance
    rows = (await db.execute(
        select(FormInstance, Project).join(Project, FormInstance.project_id == Project.id)
        .options(selectinload(FormInstance.definition), selectinload(FormInstance.events))
        .where(FormInstance.status != "submitted", FormInstance.owner_id == current_user.id)
        .order_by(FormInstance.updated_at.desc()))).all()
    out = []
    for inst, project in rows:
        out.append({"id": inst.id, "key": inst.definition.key, "title": inst.definition.title, "status": inst.status,
                    "reason": "draft", "project_id": project.id, "project_name": project.name,
                    "updated_at": inst.updated_at.isoformat()})
    return out
