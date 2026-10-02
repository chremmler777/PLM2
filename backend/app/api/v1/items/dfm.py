"""DFM archive endpoints, the same set in two scopes:

  /parts/{part_id}/dfm/...       one tool's archive (part_id must be a tool)
  /projects/{project_id}/dfm/... the project-wide "general tooling DFM"

Both routers come from one factory (_build_router) over a scope dependency
that resolves the path id to a DfmScope."""
import logging
import os
import re
from typing import Callable, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.dfm import DFM_AUDIT_ACTIONS, DfmEntry, DfmEntryFile, DfmTopic
from app.models.entities import Project
from app.models.part import Part
from app.services import dfm_audit
from app.services.dfm_service import DfmError, DfmScope, DfmService, file_path, user_names
from app.services.part_service import PartService

logger = logging.getLogger(__name__)

NOT_A_TOOL = "Only tools have a DFM archive"


class TopicCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()


async def tool_scope(part_id: int, _user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> DfmScope:
    part = await PartService.get_part(db, part_id)
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    if part.item_category != "tool":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_A_TOOL)
    return DfmScope(tool=part)


async def project_scope(project_id: int, _user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)) -> DfmScope:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return DfmScope(project=project)


def _http(e: DfmError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


async def _topic(db: AsyncSession, scope: DfmScope, topic_id: int) -> DfmTopic:
    try:
        return await DfmService.load_topic(db, scope, topic_id)
    except DfmError as e:
        raise _http(e)


async def _detail(db: AsyncSession, topic: DfmTopic, user: User) -> dict:
    await db.refresh(topic, attribute_names=["entries"])
    names = await user_names(db, DfmService.user_ids(topic))
    return DfmService.topic_detail(topic, names, user=user)


async def _load_file(db: AsyncSession, scope: DfmScope, file_id: int) -> tuple[DfmEntryFile, str, int]:
    """Files of a deleted topic cannot exist (only empty topics are deleted)."""
    found = (await db.execute(
        select(DfmEntryFile, DfmEntry.topic_id)
        .join(DfmEntry, DfmEntry.id == DfmEntryFile.entry_id)
        .join(DfmTopic, DfmTopic.id == DfmEntry.topic_id)
        .where(DfmEntryFile.id == file_id, scope.topic_filter()))).one_or_none()
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    row, topic_id = found
    path = file_path(scope, row)
    if not os.path.exists(path):
        logger.error(f"DFM file missing on disk: {path}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return row, path, topic_id


async def _audit_read(db: AsyncSession, scope: DfmScope, row: DfmEntryFile, topic_id: int, action: str,
                      user_id: int) -> None:
    """Its own small commit once serving is authorised. A read never fails
    because the audit write fails: log and serve anyway."""
    try:
        await dfm_audit.record_event(db, action=action, actor_id=user_id, **scope.kwargs(),
                                     topic_id=topic_id, entry_id=row.entry_id, file_id=row.id,
                                     details={"filename": row.original_filename})
        await db.commit()
    except Exception as e:
        logger.warning(f"DFM audit {action} for file {row.id} not written: {e}")
        try:
            await db.rollback()
        except Exception:
            pass


def _build_router(prefix: str, id_param: str, scope_dep: Callable) -> APIRouter:
    """Every DFM endpoint under {prefix}/{<id_param>}/dfm/..., the scope
    resolved by scope_dep (which reads <id_param> from the path)."""
    router = APIRouter(prefix=prefix, tags=["dfm"])
    base = "/{" + id_param + "}/dfm"

    @router.get(base + "/topics", response_model=List[dict])
    async def list_topics(scope: DfmScope = Depends(scope_dep), current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
        topics = await DfmService.list_topics(db, scope)
        names = await user_names(db, {i for t in topics for i in (t.opened_by, t.closed_by)})
        return [DfmService.topic_summary(t, names=names, user=current_user) for t in topics]

    @router.post(base + "/topics", response_model=dict, status_code=status.HTTP_201_CREATED)
    async def create_topic(body: TopicCreate, scope: DfmScope = Depends(scope_dep),
                           current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        topic = await DfmService.open_topic(db, scope, body.title, current_user.id)
        await db.commit()
        await db.refresh(topic, attribute_names=["entries"])
        names = await user_names(db, {topic.opened_by})
        return DfmService.topic_summary(topic, names=names, user=current_user)

    @router.get(base + "/topics/{topic_id}", response_model=dict)
    async def get_topic(topic_id: int, scope: DfmScope = Depends(scope_dep),
                        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        return await _detail(db, await _topic(db, scope, topic_id), current_user)

    @router.patch(base + "/topics/{topic_id}", response_model=dict)
    async def rename_topic(topic_id: int, body: TopicCreate, scope: DfmScope = Depends(scope_dep),
                           current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        """Rename, open or finished. The same title is a no-op."""
        topic = await _topic(db, scope, topic_id)
        try:
            await DfmService.rename_topic(db, scope, topic, body.title, current_user.id)
        except DfmError as e:
            raise _http(e)
        await db.commit()
        return await _detail(db, topic, current_user)

    @router.delete(base + "/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_topic(topic_id: int, scope: DfmScope = Depends(scope_dep),
                           current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        """Soft delete of an empty topic, by its opener or an admin."""
        topic = await _topic(db, scope, topic_id)
        try:
            await DfmService.delete_topic(db, scope, topic, current_user)
        except DfmError as e:
            raise _http(e)
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(base + "/topics/{topic_id}/close", response_model=dict)
    async def close_topic(topic_id: int, scope: DfmScope = Depends(scope_dep),
                          current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        topic = await _topic(db, scope, topic_id)
        try:
            await DfmService.close_topic(db, scope, topic, current_user.id)
        except DfmError as e:
            raise _http(e)
        await db.commit()
        return await _detail(db, topic, current_user)

    @router.post(base + "/topics/{topic_id}/reopen", response_model=dict)
    async def reopen_topic(topic_id: int, scope: DfmScope = Depends(scope_dep),
                           current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        topic = await _topic(db, scope, topic_id)
        try:
            await DfmService.reopen_topic(db, scope, topic, current_user.id)
        except DfmError as e:
            raise _http(e)
        await db.commit()
        return await _detail(db, topic, current_user)

    @router.post(base + "/topics/{topic_id}/entries", response_model=dict, status_code=status.HTTP_201_CREATED)
    async def create_entry(
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
        scope: DfmScope = Depends(scope_dep),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Record one ledger entry in `party`'s column, with the DFM file
        and / or a note, optionally as an update of one of that column's
        earlier entries."""
        topic = await _topic(db, scope, topic_id)
        payloads = [(f.filename or "", await f.read(), f.content_type) for f in files]
        try:
            entry = await DfmService.record_entry(
                db, scope, topic, party=party, addressed_to=addressed_to, note=note, sent_at=sent_at,
                supersedes_id=supersedes_id, files=payloads, user_id=current_user.id,
                kind=kind, reply_to_id=reply_to_id)
            await db.commit()
        except DfmError as e:
            await db.rollback()
            raise _http(e)
        except Exception as e:
            await db.rollback()
            logger.error(f"DFM entry on topic {topic_id} failed: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="Could not store the entry")
        # shaped through the topic detail so the answered / awaiting state is filled
        detail = await _detail(db, topic, current_user)
        return next(x for x in detail["entries"] if x["id"] == entry.id)

    @router.get(base + "/files/{file_id}/download")
    async def download_dfm_file(file_id: int, scope: DfmScope = Depends(scope_dep),
                                current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        row, path, topic_id = await _load_file(db, scope, file_id)
        filename = row.original_filename
        await _audit_read(db, scope, row, topic_id, "file_downloaded", current_user.id)
        return FileResponse(path=path, filename=filename, media_type="application/octet-stream")

    @router.get(base + "/files/{file_id}/inline")
    async def inline_dfm_file(file_id: int, scope: DfmScope = Depends(scope_dep),
                              current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        """PDF for the document pane. Everything else downloads."""
        row, path, topic_id = await _load_file(db, scope, file_id)
        filename = row.original_filename
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Only PDF can be shown inline")
        await _audit_read(db, scope, row, topic_id, "file_viewed", current_user.id)
        return FileResponse(path=path, media_type="application/pdf", filename=filename,
                            content_disposition_type="inline")

    # ---- audit trail (read only; events are written by the actions above) ------

    async def _audit_topic(db: AsyncSession, scope: DfmScope, topic_id: int) -> None:
        """The topic filter accepts a deleted topic of this scope: its trail stays readable."""
        found = (await db.execute(select(DfmTopic.id).where(
            DfmTopic.id == topic_id, scope.topic_filter()))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")

    @router.get(base + "/audit", response_model=List[dict])
    async def list_audit(topic_id: Optional[int] = None, action: Optional[str] = None,
                         limit: int = Query(dfm_audit.DEFAULT_LIMIT, ge=1, le=dfm_audit.MAX_LIMIT),
                         before_id: Optional[int] = Query(None, ge=1),
                         scope: DfmScope = Depends(scope_dep),
                         current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        """Newest first. Page with before_id = the last id of the previous page."""
        if topic_id is not None:
            await _audit_topic(db, scope, topic_id)
        if action is not None and action not in DFM_AUDIT_ACTIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Unknown action '{action}'. Valid: {', '.join(DFM_AUDIT_ACTIONS)}")
        events = await dfm_audit.list_events(db, scope, topic_id=topic_id, action=action, limit=limit,
                                             before_id=before_id)
        return await dfm_audit.shape_events(db, events)

    @router.get(base + "/audit.csv")
    async def audit_csv(topic_id: Optional[int] = None, scope: DfmScope = Depends(scope_dep),
                        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        """The whole trail (or one topic's) as CSV for Excel, newest first."""
        if topic_id is not None:
            await _audit_topic(db, scope, topic_id)
        events = await dfm_audit.list_events(db, scope, topic_id=topic_id, limit=None)
        body = dfm_audit.to_csv(await dfm_audit.shape_events(db, events))
        number = re.sub(r"[^A-Za-z0-9._-]+", "_", scope.label)
        filename = f"dfm-audit-{number}" + (f"-topic-{topic_id}" if topic_id is not None else "") + ".csv"
        return Response(content=body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    return router


router = _build_router("/parts", "part_id", tool_scope)
project_router = _build_router("/projects", "project_id", project_scope)
