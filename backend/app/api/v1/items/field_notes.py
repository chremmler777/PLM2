"""Field notes (comments and a flag per field) on parts, and every note of a
project for the worksheet. Org scoping as in part_paint.py: a part or project
of another organization is 404."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _part_in_org, _project_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.part import Part
from app.services.field_note_service import FieldNoteError, FieldNoteService, check_field_key

router = APIRouter(tags=["field-notes"])


class CommentIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class FlagIn(BaseModel):
    status: Optional[Literal["open", "confirmed", "rejected"]] = None


async def _part(db: AsyncSession, part_id: int, user: User) -> Part:
    await _part_in_org(db, part_id, user.organization_id)
    return await db.get(Part, part_id)


def _bad_request(e: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/parts/{part_id}/field-notes", response_model=List[dict])
async def list_part_notes(part_id: int, field_key: Optional[str] = Query(None),
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id, current_user)
    notes = await FieldNoteService.list_for_part(db, part.id, field_key)
    names = await FieldNoteService.names_for(db, notes)
    return [FieldNoteService.summary(n, names) for n in notes]


@router.get("/parts/{part_id}/field-notes/{field_key}", response_model=dict)
async def get_note_thread(part_id: int, field_key: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id, current_user)
    try:
        check_field_key(part, field_key)
    except FieldNoteError as e:
        raise _bad_request(e)
    note = await FieldNoteService.get(db, part.id, field_key)
    if note is None:
        return FieldNoteService.empty_thread(part.id, field_key)
    return FieldNoteService.thread(note, await FieldNoteService.names_for(db, [note]))


@router.post("/parts/{part_id}/field-notes/{field_key}/comments", response_model=dict,
             status_code=status.HTTP_201_CREATED)
async def add_note_comment(part_id: int, field_key: str, body: CommentIn,
                           current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id, current_user)
    try:
        note = await FieldNoteService.add_comment(db, part, field_key, body.body, current_user.id)
    except FieldNoteError as e:
        await db.rollback()
        raise _bad_request(e)
    out = FieldNoteService.thread(note, await FieldNoteService.names_for(db, [note]))
    await db.commit()
    return out


@router.put("/parts/{part_id}/field-notes/{field_key}/flag", response_model=dict)
async def set_note_flag(part_id: int, field_key: str, body: FlagIn,
                        current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    part = await _part(db, part_id, current_user)
    try:
        note = await FieldNoteService.set_flag(db, part, field_key, body.status, current_user.id)
    except FieldNoteError as e:
        await db.rollback()
        raise _bad_request(e)
    if note is None:
        out = FieldNoteService.empty_thread(part.id, field_key)
    else:
        out = FieldNoteService.thread(note, await FieldNoteService.names_for(db, [note]))
    await db.commit()
    return out


@router.get("/projects/{project_id}/field-notes", response_model=List[dict])
async def list_project_notes(project_id: int, current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    await _project_in_org(db, project_id, current_user.organization_id)
    notes = await FieldNoteService.list_for_project(db, project_id)
    names = await FieldNoteService.names_for(db, notes)
    return [FieldNoteService.summary(n, names) for n in notes]
