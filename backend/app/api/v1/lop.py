"""Project LOP (list of open points): PM tasks, comments, history.
Everything under /v1/lop. Everyone logged in reads; writes follow the rules
in app/services/lop_service.py."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
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
    can_manage = await LopService.can_manage(db, user, project_id)
    lines = await LopService.lines_for_project(db, project_id, view)
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
