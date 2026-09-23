"""DFM archive endpoints: /parts/{part_id}/dfm/... . part_id must be a tool."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.part import Part
from app.services.dfm_service import DfmError, DfmService, user_names
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
            supersedes_id=supersedes_id, files=payloads, user_id=current_user.id)
        await db.commit()
    except DfmError as e:
        await db.rollback()
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"DFM entry on topic {topic_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not store the entry")
    names = await user_names(db, {current_user.id})
    d = DfmService.entry_dict(entry, names)
    d["history"] = []
    if entry.supersedes_id:
        await db.refresh(topic, attribute_names=["entries"])
        names = await user_names(db, DfmService.user_ids(topic))
        detail = DfmService.topic_detail(topic, names)
        d = next(x for x in detail["entries"] if x["id"] == entry.id)
    return d
