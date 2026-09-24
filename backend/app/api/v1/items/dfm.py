"""DFM archive endpoints: /parts/{part_id}/dfm/... . part_id must be a tool."""
import logging
import os
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.dfm import DFM_AUDIT_ACTIONS, DfmEntry, DfmEntryFile, DfmTopic
from app.models.part import Part
from app.services import dfm_audit
from app.services.dfm_service import DfmError, DfmService, file_path, user_names
from app.services.part_service import PartService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parts", tags=["dfm"])

NOT_A_TOOL = "Only tools have a DFM archive"


class TopicCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()


async def _load_tool(db: AsyncSession, part_id: int) -> Part:
    part = await PartService.get_part(db, part_id)
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    if part.item_category != "tool":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_A_TOOL)
    return part


async def _topic(db: AsyncSession, tool: Part, topic_id: int):
    try:
        return await DfmService.load_topic(db, tool.id, topic_id)
    except DfmError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


async def _detail(db: AsyncSession, topic) -> dict:
    await db.refresh(topic, attribute_names=["entries"])
    names = await user_names(db, DfmService.user_ids(topic))
    return DfmService.topic_detail(topic, names)


@router.get("/{part_id}/dfm/topics", response_model=List[dict])
async def list_topics(part_id: int, current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    return [DfmService.topic_summary(t) for t in await DfmService.list_topics(db, tool.id)]


@router.post("/{part_id}/dfm/topics", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_topic(part_id: int, body: TopicCreate, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    topic = await DfmService.open_topic(db, tool, body.title, current_user.id)
    await db.commit()
    await db.refresh(topic, attribute_names=["entries"])
    return DfmService.topic_summary(topic)


@router.get("/{part_id}/dfm/topics/{topic_id}", response_model=dict)
async def get_topic(part_id: int, topic_id: int, current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    return await _detail(db, await _topic(db, tool, topic_id))


@router.post("/{part_id}/dfm/topics/{topic_id}/close", response_model=dict)
async def close_topic(part_id: int, topic_id: int, current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    topic = await _topic(db, tool, topic_id)
    try:
        await DfmService.close_topic(db, tool, topic, current_user.id)
    except DfmError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    await db.commit()
    return await _detail(db, topic)


@router.post("/{part_id}/dfm/topics/{topic_id}/reopen", response_model=dict)
async def reopen_topic(part_id: int, topic_id: int, current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    topic = await _topic(db, tool, topic_id)
    try:
        await DfmService.reopen_topic(db, tool, topic, current_user.id)
    except DfmError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    await db.commit()
    return await _detail(db, topic)


@router.post("/{part_id}/dfm/topics/{topic_id}/entries", response_model=dict,
             status_code=status.HTTP_201_CREATED)
async def create_entry(
    part_id: int,
    topic_id: int,
    party: str = Form(...),
    addressed_to: str = Form(..., description="JSON list of the other parties"),
    note: Optional[str] = Form(None),
    sent_at: Optional[str] = Form(None),
    supersedes_id: Optional[int] = Form(None),
    kind: Optional[str] = Form(None, description="original | forward | answer | question; default original, "
                                                "an update inherits the kind of what it updates"),
    reply_to_id: Optional[int] = Form(None, description="the message forwarded, answered or asked about"),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record one ledger entry in `party`'s column, optionally with files and
    as an update of one of that column's earlier entries."""
    tool = await _load_tool(db, part_id)
    topic = await _topic(db, tool, topic_id)
    payloads = [(f.filename or "", await f.read(), f.content_type) for f in files]
    try:
        entry = await DfmService.record_entry(
            db, tool, topic, party=party, addressed_to=addressed_to, note=note, sent_at=sent_at,
            supersedes_id=supersedes_id, files=payloads, user_id=current_user.id,
            kind=kind, reply_to_id=reply_to_id)
        await db.commit()
    except DfmError as e:
        await db.rollback()
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"DFM entry on topic {topic_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not store the entry")
    # shaped through the topic detail so the answered / awaiting state is filled
    await db.refresh(topic, attribute_names=["entries"])
    names = await user_names(db, DfmService.user_ids(topic))
    detail = DfmService.topic_detail(topic, names)
    return next(x for x in detail["entries"] if x["id"] == entry.id)


async def _load_file(db: AsyncSession, tool: Part, file_id: int) -> tuple[DfmEntryFile, str, int]:
    found = (await db.execute(
        select(DfmEntryFile, DfmEntry.topic_id)
        .join(DfmEntry, DfmEntry.id == DfmEntryFile.entry_id)
        .join(DfmTopic, DfmTopic.id == DfmEntry.topic_id)
        .where(DfmEntryFile.id == file_id, DfmTopic.tool_part_id == tool.id))).one_or_none()
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    row, topic_id = found
    path = file_path(tool.id, row)
    if not os.path.exists(path):
        logger.error(f"DFM file missing on disk: {path}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return row, path, topic_id


async def _audit_read(db: AsyncSession, tool: Part, row: DfmEntryFile, topic_id: int, action: str,
                      user_id: int) -> None:
    """Its own small commit once serving is authorised. A read never fails
    because the audit write fails: log and serve anyway."""
    try:
        await dfm_audit.record_event(db, tool_part_id=tool.id, action=action, actor_id=user_id,
                                     topic_id=topic_id, entry_id=row.entry_id, file_id=row.id,
                                     details={"filename": row.original_filename})
        await db.commit()
    except Exception as e:
        logger.warning(f"DFM audit {action} for file {row.id} not written: {e}")
        try:
            await db.rollback()
        except Exception:
            pass


@router.get("/{part_id}/dfm/files/{file_id}/download")
async def download_dfm_file(part_id: int, file_id: int, current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    tool = await _load_tool(db, part_id)
    row, path, topic_id = await _load_file(db, tool, file_id)
    filename = row.original_filename
    await _audit_read(db, tool, row, topic_id, "file_downloaded", current_user.id)
    return FileResponse(path=path, filename=filename, media_type="application/octet-stream")


@router.get("/{part_id}/dfm/files/{file_id}/inline")
async def inline_dfm_file(part_id: int, file_id: int, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """PDF for the document pane. Everything else downloads."""
    tool = await _load_tool(db, part_id)
    row, path, topic_id = await _load_file(db, tool, file_id)
    filename = row.original_filename
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF can be shown inline")
    await _audit_read(db, tool, row, topic_id, "file_viewed", current_user.id)
    return FileResponse(path=path, media_type="application/pdf", filename=filename,
                        content_disposition_type="inline")


# ---- audit trail (read only; events are written by the actions above) ----------

@router.get("/{part_id}/dfm/audit", response_model=List[dict])
async def list_audit(part_id: int, topic_id: Optional[int] = None, action: Optional[str] = None,
                     limit: int = Query(dfm_audit.DEFAULT_LIMIT, ge=1, le=dfm_audit.MAX_LIMIT),
                     before_id: Optional[int] = Query(None, ge=1),
                     current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Newest first. Page with before_id = the last id of the previous page."""
    tool = await _load_tool(db, part_id)
    if topic_id is not None:
        await _topic(db, tool, topic_id)
    if action is not None and action not in DFM_AUDIT_ACTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Unknown action '{action}'. Valid: {', '.join(DFM_AUDIT_ACTIONS)}")
    events = await dfm_audit.list_events(db, tool.id, topic_id=topic_id, action=action, limit=limit,
                                         before_id=before_id)
    return await dfm_audit.shape_events(db, events)


@router.get("/{part_id}/dfm/audit.csv")
async def audit_csv(part_id: int, topic_id: Optional[int] = None,
                    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The whole trail (or one topic's) as CSV for Excel, newest first."""
    tool = await _load_tool(db, part_id)
    if topic_id is not None:
        await _topic(db, tool, topic_id)
    events = await dfm_audit.list_events(db, tool.id, topic_id=topic_id, limit=None)
    body = dfm_audit.to_csv(await dfm_audit.shape_events(db, events))
    number = re.sub(r"[^A-Za-z0-9._-]+", "_", tool.part_number or str(tool.id))
    filename = f"dfm-audit-{number}" + (f"-topic-{topic_id}" if topic_id is not None else "") + ".csv"
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
