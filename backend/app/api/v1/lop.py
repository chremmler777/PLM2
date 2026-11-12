"""Project LOP (list of open points): PM tasks, comments, history.
Everything under /v1/lop. Everyone logged in reads; writes follow the rules
in app/services/lop_service.py."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services import lop_sources, pdb_client
from app.services.lop_service import LopError, LopService

router = APIRouter(prefix="/lop", tags=["lop"])


class LineCreate(BaseModel):
    title: str
    department_id: Optional[int] = None
    due_date: Optional[date] = None
    next_check_date: Optional[date] = None
    responsible_id: Optional[int] = None


class LinePatch(BaseModel):
    title: Optional[str] = None
    department_id: Optional[int] = None
    responsible_id: Optional[int] = None
    clear_responsible: bool = False
    due_date: Optional[date] = None
    next_check_date: Optional[date] = None
    status: Optional[Literal["new", "open", "in_work", "done_check", "closed"]] = None
    reason: Optional[str] = None


class FromSep(BaseModel):
    item_id: Optional[int] = None
    due_date: Optional[date] = None
    gate_id: Optional[int] = None
    only_open: bool = False


class PinIn(BaseModel):
    responsible_id: Optional[int] = None
    due_date: Optional[date] = None
    next_check_date: Optional[date] = None


class CommentIn(BaseModel):
    text: str


def _http(e: LopError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


async def _one(db: AsyncSession, user: User, line, can_manage: Optional[bool] = None) -> dict:
    if can_manage is None:
        can_manage = await LopService.can_manage(db, user, line.project_id)
    ctx = await LopService.context(db, user, [line], can_manage=can_manage)
    return LopService.line_dict(line, ctx)


@router.get("/mine")
async def mine(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The caller's open lines across all projects with LOP switched on."""
    rows = await LopService.my_open_lines(db, user)
    # lines whose source closed since the last visit leave the list (no form writes here)
    synced = {p.id for ln, p in rows if ln.kind in lop_sources.SOURCE_KINDS}
    for pid in synced:
        await lop_sources.sync_project_lines(db, pid, user.id, full=False)
    if synced:
        rows = await LopService.my_open_lines(db, user)
    ctx = await LopService.context(db, user, [ln for ln, _ in rows], can_manage=False)
    out = []
    for line, project in rows:
        d = LopService.line_dict(line, ctx)
        d["can_manage"] = await LopService.can_manage(db, user, line.project_id)
        d["can_report"] = not d["can_manage"] and line.status != "closed"
        d.update(project_code=project.code, project_name=project.name)
        out.append(d)
    return out


@router.get("/projects/{project_id}")
async def project_lop(project_id: int, view: Literal["meeting", "open", "closed"] = Query("open"),
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        project = await LopService.get_project(db, project_id, user)
    except LopError as e:
        raise _http(e)
    await lop_sources.sync_project_lines(db, project_id, user.id)   # risk rows only
    can_manage = await LopService.can_manage(db, user, project_id)
    lines = [ln for ln in await LopService.lines_for_project(db, project_id, view)
             if ln.kind != "pdb_topic"]      # PDB topics come from /pdb only
    ctx = await LopService.context(db, user, lines, can_manage=can_manage)
    return {
        "project": {"id": project.id, "code": project.code, "name": project.name,
                    "lop_enabled": project.lop_enabled},
        "can_manage": can_manage,
        "lines": [LopService.line_dict(ln, ctx) for ln in lines],
        "last_meeting": None,
    }


@router.post("/projects/{project_id}/lines", status_code=201)
async def create_line(project_id: int, body: LineCreate,
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        line = await LopService.create_task(db, user, project_id, **body.model_dump())
    except LopError as e:
        raise _http(e)
    return await _one(db, user, line)


@router.get("/projects/{project_id}/sep-candidates")
async def sep_candidates(project_id: int, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Open SEP items that are not on the LOP yet, by gate."""
    try:
        await LopService.get_project(db, project_id, user)
    except LopError as e:
        raise _http(e)
    return {"gates": await lop_sources.sep_candidates(db, project_id)}


@router.post("/projects/{project_id}/lines/from-sep", status_code=201)
async def add_from_sep(project_id: int, body: FromSep, response: Response,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The PM adds one SEP item `{item_id, due_date?}` or all open items of a
    gate `{gate_id, only_open: true}`. Nothing from SEP enters the LOP otherwise."""
    if (body.item_id is None) == (body.gate_id is None):
        raise HTTPException(400, "Send item_id or gate_id")
    try:
        if body.item_id is not None:
            line, created = await lop_sources.add_sep_item(
                db, user, project_id, body.item_id, body.due_date)
            if not created:
                response.status_code = 200
            return await _one(db, user, line)
        if not body.only_open:
            raise HTTPException(400, "Adding a gate needs only_open: true")
        lines = await lop_sources.add_sep_gate(db, user, project_id, body.gate_id)
    except LopError as e:
        raise _http(e)
    ctx = await LopService.context(db, user, lines, can_manage=True)
    return {"added": len(lines), "lines": [LopService.line_dict(ln, ctx) for ln in lines]}


@router.patch("/lines/{line_id}")
async def patch_line(line_id: int, body: LinePatch,
                     user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sent = body.model_dump(exclude_unset=True)
    reason = sent.pop("reason", None)
    if sent.get("status") is None:
        sent.pop("status", None)
    if not sent.get("clear_responsible"):
        sent.pop("clear_responsible", None)
    try:
        line = await LopService.update_line(db, user, line_id, sent, reason)
    except LopError as e:
        raise _http(e)
    return await _one(db, user, line)


@router.post("/lines/{line_id}/comments", status_code=201)
async def add_comment(line_id: int, body: CommentIn,
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        c = await LopService.add_comment(db, user, line_id, body.text)
    except LopError as e:
        raise _http(e)
    return {"id": c.id, "line_id": c.line_id, "user_id": c.user_id, "text": c.text,
            "created_at": c.created_at.isoformat()}


@router.get("/lines/{line_id}/history")
async def history(line_id: int, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    try:
        return await LopService.history(db, user, line_id)
    except LopError as e:
        raise _http(e)


PDB_UNPINNED_SHOWN = 10


@router.get("/projects/{project_id}/pdb")
async def project_pdb(project_id: int, all: bool = Query(False),
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The project's live PDB status and open topics. Default: escalated and
    pinned topics plus the 10 oldest of the rest (`hidden` counts the others);
    `all=true` returns every topic. PDB being down is `available: false`."""
    try:
        project = await LopService.get_project(db, project_id, user)
    except LopError as e:
        raise _http(e)
    can_manage = await LopService.can_manage(db, user, project_id)
    try:
        topics = await pdb_client.project_topics(project.code)
    except pdb_client.PdbUnavailable as e:
        return {"available": False, "reason": str(e), "status": None, "topics": [], "hidden": 0}
    status, status_reason = None, None
    try:
        status = await pdb_client.project_status(project.code)
    except pdb_client.PdbUnavailable as e:
        status_reason = str(e)          # topics still work; only the status block is missing
    # PDB answered with the full open list: pins follow it
    pins = await LopService.follow_pdb(db, project_id, {str(t["id"]) for t in topics})
    pinned = {ln.ref_key: ln for ln in pins if ln.status != "closed"}
    by_id = {str(t["id"]): t for t in topics}
    ctx = await LopService.context(db, user, list(pinned.values()), can_manage=can_manage)
    ctx.pdb = by_id

    def age(t: dict) -> int:
        return t.get("age_days") or 0
    def tie(t: dict) -> int:
        try:
            return -int(t["id"])
        except (TypeError, ValueError):
            return 0
    ordered = sorted(topics, key=lambda t: (not t.get("escalated"), -age(t), tie(t)))
    rest = [t for t in ordered if not t.get("escalated") and str(t["id"]) not in pinned]
    left_out = {str(t["id"]) for t in rest[PDB_UNPINNED_SHOWN:]} if not all else set()
    out = []
    for t in ordered:
        key = str(t["id"])
        if key in left_out:
            continue
        out.append(LopService.line_dict(pinned[key], ctx) if key in pinned
                   else LopService.pdb_topic_dict(t, ctx))
    return {"available": True, "reason": None, "status": status,
            "status_reason": status_reason, "topics": out,
            "hidden": len(left_out)}


@router.post("/projects/{project_id}/pdb/{topic_id}/pin")
async def pin_pdb_topic(project_id: int, topic_id: int, body: PinIn, response: Response,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The PM gives an open PDB topic a responsible person and a date."""
    try:
        project = await LopService.get_project(db, project_id, user)
        if not await LopService.can_manage(db, user, project_id):
            raise HTTPException(403, "Only the Project Manager pins a PDB topic")
        if body.due_date is None and body.next_check_date is None:
            raise HTTPException(400, "A pinned topic needs a due date or a next-check date")
        try:
            topics = await pdb_client.project_topics(project.code)
        except pdb_client.PdbUnavailable as e:
            raise HTTPException(503, str(e))
        topic = next((t for t in topics if str(t["id"]) == str(topic_id)), None)
        if topic is None:
            raise HTTPException(404, "This topic is not open in PDB")
        line, created = await LopService.pin_pdb_topic(
            db, user, project_id, topic, responsible_id=body.responsible_id,
            due_date=body.due_date, next_check_date=body.next_check_date)
    except LopError as e:
        raise _http(e)
    response.status_code = 201 if created else 200
    ctx = await LopService.context(db, user, [line], can_manage=True)
    ctx.pdb = {str(topic["id"]): topic}
    return LopService.line_dict(line, ctx)
