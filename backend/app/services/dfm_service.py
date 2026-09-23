"""DFM archive service: topics per tool, append-only entries in three columns,
files on disk under uploads/dfm/<tool>/<entry>/. Nothing is deleted; an
update is a new entry that supersedes the old one."""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dfm import (
    DfmEntry, DfmEntryFile, DfmTopic, DFM_PARTIES, DFM_TOPIC_FINISHED, DFM_TOPIC_OPEN,
)
from app.models.entities import User
from app.models.part import Part
from app.services.part_service import ChangelogService

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB, same as revision files
TOPIC_CLOSED_MESSAGE = "Topic is finished, reopen it first"
ALREADY_SUPERSEDED_MESSAGE = "This entry was already updated, refresh"
MAX_FILENAME_LEN = 255
MAX_CONTENT_TYPE_LEN = 100


class DfmError(ValueError):
    """Rule violation; .status is the HTTP status the router answers with."""
    status = 400

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        if status is not None:
            self.status = status


class DfmClosed(DfmError):
    status = 409


def dfm_dir(tool_part_id: int, entry_id: int) -> str:
    return os.path.join(os.getcwd(), "uploads", "dfm", str(tool_part_id), str(entry_id))


def file_path(tool_part_id: int, f: DfmEntryFile) -> str:
    return os.path.join(dfm_dir(tool_part_id, f.entry_id), f.saved_filename)


def _iso(v: datetime | date | None) -> str | None:
    return v.isoformat() if v else None


async def user_names(session: AsyncSession, user_ids: set) -> dict:
    """id -> display name in one query; lists never resolve users per row."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await session.execute(
        select(User.id, User.full_name, User.username).where(User.id.in_(ids)))).all()
    return {uid: (full or username) for uid, full, username in rows}


def parse_addressed_to(raw: str | list | None, party: str) -> list[str]:
    """The form sends addressed_to as a JSON string; accept a list too. It must
    name one or two of the *other* parties."""
    if raw is None or raw == "":
        raise DfmError("addressed_to is required")
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise DfmError("addressed_to must be a JSON list of parties")
    if not isinstance(value, list) or not value:
        raise DfmError("addressed_to must name at least one other party")
    seen: list[str] = []
    for p in value:
        if p not in DFM_PARTIES:
            raise DfmError(f"Unknown party '{p}'. Valid: {', '.join(DFM_PARTIES)}")
        if p == party:
            raise DfmError("An entry cannot be addressed to its own party")
        if p not in seen:
            seen.append(p)
    return seen


def truncate_filename(name: str, limit: int = MAX_FILENAME_LEN) -> str:
    """Keep the extension when a filename is longer than the column limit."""
    if len(name) <= limit:
        return name
    base, ext = os.path.splitext(name)
    if len(ext) >= limit:
        return name[:limit]
    return base[: limit - len(ext)] + ext


def parse_sent_at(raw: str | None) -> date | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise DfmError("sent_at must be a date (YYYY-MM-DD)")


class DfmService:

    @staticmethod
    async def load_topic(session: AsyncSession, tool_part_id: int, topic_id: int) -> DfmTopic:
        topic = (await session.execute(select(DfmTopic).where(
            DfmTopic.id == topic_id, DfmTopic.tool_part_id == tool_part_id))).scalar_one_or_none()
        if topic is None:
            raise DfmError("Topic not found", status=404)
        return topic

    @staticmethod
    async def list_topics(session: AsyncSession, tool_part_id: int) -> list[DfmTopic]:
        return list((await session.execute(
            select(DfmTopic).where(DfmTopic.tool_part_id == tool_part_id)
            .order_by(DfmTopic.opened_at.desc(), DfmTopic.id.desc()))).scalars().all())

    @staticmethod
    async def open_topic(session: AsyncSession, tool: Part, title: str, user_id: int) -> DfmTopic:
        topic = DfmTopic(tool_part_id=tool.id, title=title.strip(), opened_by=user_id)
        session.add(topic)
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=tool.id, action="dfm_topic_opened",
            action_description=f"DFM topic opened: {topic.title}", performed_by=user_id)
        return topic

    @staticmethod
    async def close_topic(session: AsyncSession, tool: Part, topic: DfmTopic, user_id: int) -> DfmTopic:
        if topic.status == DFM_TOPIC_FINISHED:
            raise DfmClosed("Topic is already finished")
        topic.status = DFM_TOPIC_FINISHED
        topic.closed_by = user_id
        topic.closed_at = datetime.utcnow()
        await ChangelogService.log_action(
            session, part_id=tool.id, action="dfm_topic_closed",
            action_description=f"DFM topic finished confirmed: {topic.title}", performed_by=user_id)
        return topic

    @staticmethod
    async def reopen_topic(session: AsyncSession, tool: Part, topic: DfmTopic, user_id: int) -> DfmTopic:
        if topic.status == DFM_TOPIC_OPEN:
            raise DfmClosed("Topic is already open")
        topic.status = DFM_TOPIC_OPEN
        topic.closed_by = None
        topic.closed_at = None
        await ChangelogService.log_action(
            session, part_id=tool.id, action="dfm_topic_reopened",
            action_description=f"DFM topic reopened: {topic.title}", performed_by=user_id)
        return topic

    @staticmethod
    async def record_entry(session: AsyncSession, tool: Part, topic: DfmTopic, *, party: str,
                           addressed_to: str | list | None, note: str | None, sent_at: str | None,
                           supersedes_id: int | None, files: list[tuple[str, bytes, str | None]],
                           user_id: int) -> DfmEntry:
        """files: (original filename, bytes, content type). The row is flushed
        first for its id, the files are written, then the file rows are added;
        the caller commits. A failed write removes what was written and raises,
        so nothing is recorded."""
        if topic.status != DFM_TOPIC_OPEN:
            raise DfmClosed(TOPIC_CLOSED_MESSAGE)
        if party not in DFM_PARTIES:
            raise DfmError(f"Unknown party '{party}'. Valid: {', '.join(DFM_PARTIES)}")
        targets = parse_addressed_to(addressed_to, party)
        sent = parse_sent_at(sent_at)
        if supersedes_id is not None:
            old = await session.get(DfmEntry, supersedes_id)
            if old is None or old.topic_id != topic.id:
                raise DfmError("The entry to update is not in this topic")
            if old.party != party:
                raise DfmError("An entry can only be updated from its own column")
            successor = (await session.execute(
                select(DfmEntry.id).where(DfmEntry.supersedes_id == old.id))).scalar_one_or_none()
            if successor is not None:
                raise DfmClosed(ALREADY_SUPERSEDED_MESSAGE)
        for name, contents, _ in files:
            if not (name or "").strip():
                raise DfmError("A file needs a filename")
            if len(contents) > MAX_FILE_SIZE:
                raise DfmError(f"File {name} is over 100MB")

        entry = DfmEntry(topic_id=topic.id, party=party, addressed_to=targets,
                         note=(note or "").strip() or None, sent_at=sent,
                         supersedes_id=supersedes_id, recorded_by=user_id)
        session.add(entry)
        await session.flush()

        target_dir = dfm_dir(tool.id, entry.id)
        written: list[str] = []
        try:
            if files:
                os.makedirs(target_dir, exist_ok=True)
            for name, contents, content_type in files:
                ext = os.path.splitext(name)[1].lower()
                saved = f"{uuid.uuid4().hex}{ext}"
                path = os.path.join(target_dir, saved)
                with open(path, "wb") as fh:
                    fh.write(contents)
                written.append(path)
                stored_type = (content_type or mimetypes.guess_type(name)[0] or "application/octet-stream")
                session.add(DfmEntryFile(
                    entry_id=entry.id, original_filename=truncate_filename(name), saved_filename=saved,
                    file_size=len(contents),
                    content_type=stored_type[:MAX_CONTENT_TYPE_LEN],
                    uploaded_by=user_id))
            await session.flush()
            await session.refresh(entry, attribute_names=["files"])
            what = "updated" if supersedes_id else "recorded"
            await ChangelogService.log_action(
                session, part_id=tool.id, action="dfm_entry_recorded",
                action_description=f"DFM entry {what} in {topic.title} by {party} to {', '.join(targets)}"
                                   + (f" with {len(files)} file(s)" if files else ""),
                performed_by=user_id)
        except Exception:
            for path in written:
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise
        return entry

    # ---- response shaping -------------------------------------------------

    @staticmethod
    def topic_summary(topic: DfmTopic) -> dict:
        stamps = [topic.opened_at] + [e.recorded_at for e in topic.entries]
        if topic.closed_at:
            stamps.append(topic.closed_at)
        return {
            "id": topic.id, "tool_part_id": topic.tool_part_id, "title": topic.title,
            "status": topic.status,
            "opened_by": topic.opened_by, "opened_at": _iso(topic.opened_at),
            "closed_by": topic.closed_by, "closed_at": _iso(topic.closed_at),
            "entry_count": len(topic.entries),
            "last_activity": _iso(max(s for s in stamps if s is not None)),
        }

    @staticmethod
    def file_dict(f: DfmEntryFile, names: dict) -> dict:
        return {
            "id": f.id, "entry_id": f.entry_id, "original_filename": f.original_filename,
            "file_size": f.file_size, "content_type": f.content_type,
            "uploaded_by": f.uploaded_by, "uploaded_by_name": names.get(f.uploaded_by),
            "uploaded_at": _iso(f.uploaded_at),
        }

    @staticmethod
    def entry_dict(e: DfmEntry, names: dict) -> dict:
        return {
            "id": e.id, "topic_id": e.topic_id, "party": e.party,
            "addressed_to": list(e.addressed_to or []), "note": e.note,
            "sent_at": _iso(e.sent_at), "supersedes_id": e.supersedes_id,
            "recorded_by": e.recorded_by, "recorded_by_name": names.get(e.recorded_by),
            "recorded_at": _iso(e.recorded_at),
            "files": [DfmService.file_dict(f, names) for f in e.files],
        }

    @staticmethod
    def topic_detail(topic: DfmTopic, names: dict) -> dict:
        """Entries in the order they were received: by sent_at when it is
        set, else the date they were recorded, then recorded_at, then id.
        This lets a backfilled mail dated earlier sit above one recorded
        earlier but sent later. Each supersede chain is collapsed onto its
        newest entry; `history` lists the earlier versions, newest first."""
        by_id = {e.id: e for e in topic.entries}
        superseded = {e.supersedes_id for e in topic.entries if e.supersedes_id is not None}
        ordered = sorted(
            topic.entries,
            key=lambda e: (e.sent_at or e.recorded_at.date(), e.recorded_at, e.id))
        entries = []
        for e in ordered:
            if e.id in superseded:
                continue
            d = DfmService.entry_dict(e, names)
            history = []
            cursor = by_id.get(e.supersedes_id) if e.supersedes_id else None
            while cursor is not None:
                history.append(DfmService.entry_dict(cursor, names))
                cursor = by_id.get(cursor.supersedes_id) if cursor.supersedes_id else None
            d["history"] = history
            entries.append(d)
        return {**DfmService.topic_summary(topic), "entries": entries}

    @staticmethod
    def user_ids(topic: DfmTopic) -> set:
        ids = {topic.opened_by, topic.closed_by}
        for e in topic.entries:
            ids.add(e.recorded_by)
            ids.update(f.uploaded_by for f in e.files)
        return ids
