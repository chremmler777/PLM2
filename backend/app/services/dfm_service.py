"""DFM archive service: topics per tool, append-only entries in three columns,
files on disk under uploads/dfm/<tool>/<entry>/. Nothing is deleted; an
update is a new entry that supersedes the old one."""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dfm import (
    DfmEntry, DfmEntryFile, DfmTopic, DFM_KIND_ORIGINAL, DFM_KINDS, DFM_PARTIES, DFM_TOPIC_FINISHED,
    DFM_TOPIC_OPEN,
)
from app.models.entities import User
from app.models.part import Part
from app.services import dfm_audit
from app.services.part_service import ChangelogService

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB, same as revision files
TOPIC_CLOSED_MESSAGE = "Topic is finished, reopen it first"
ALREADY_SUPERSEDED_MESSAGE = "This entry was already updated, refresh"
MAX_FILENAME_LEN = 255
MAX_CONTENT_TYPE_LEN = 100
# kinds whose addressees owe an answer
DFM_AWAITING_KINDS = ("original", "forward", "question")


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


def parse_kind(raw: str | None) -> str | None:
    """None when not given (an update then inherits the kind)."""
    if raw is None or raw.strip() == "":
        return None
    kind = raw.strip()
    if kind not in DFM_KINDS:
        raise DfmError(f"Unknown kind '{kind}'. Valid: {', '.join(DFM_KINDS)}")
    return kind


def check_flow(topic: DfmTopic, party: str, targets: list[str], kind: str, reply_to: DfmEntry | None,
               reply_to_id: int | None) -> None:
    """The spec's rules on who may answer, ask again or forward what."""
    if kind == DFM_KIND_ORIGINAL:
        if reply_to_id is not None:
            raise DfmError("An original has no reply link")
        return
    if reply_to_id is None:
        raise DfmError(f"A {kind} needs the message it replies to")
    if reply_to is None or reply_to.topic_id != topic.id:
        raise DfmError("The message replied to is not in this topic")
    received = list(reply_to.addressed_to or [])
    if kind == "forward":
        if party != "ktx":
            raise DfmError("Only KTX forwards messages")
        if "ktx" not in received:
            raise DfmError("KTX can only forward a message it received")
        if any(t == reply_to.party or t in received for t in targets):
            raise DfmError("A forward goes to a party that has not had the message yet")
        return
    if kind == "question":
        if reply_to.kind != "answer":
            raise DfmError("A question must reply to an answer")
        if party not in received:
            raise DfmError("Only a party the answer was addressed to can ask again on it")
        if reply_to.party not in targets:
            raise DfmError("A question must be addressed to the sender of the answer it asks about")
        return
    # answer
    if party not in received:
        raise DfmError("Only a party the message was addressed to can answer it")
    if reply_to.party not in targets:
        raise DfmError("An answer must be addressed to the sender of the message it replies to")


def _msg_date(e: DfmEntry) -> date:
    """The mail date when set, else the day it was recorded."""
    return e.sent_at or e.recorded_at.date()


def _order_key(e: DfmEntry):
    return (_msg_date(e), e.recorded_at, e.id)


def flow_state(topic: DfmTopic, today: date | None = None) -> dict:
    """Answered or waiting, derived from the entries, never stored.

    For each current (not superseded) original, forward and question, every
    addressee is either answered (a current answer from that party replies
    to any version of the message) or awaiting since the message date."""
    today = today or date.today()
    entries = list(topic.entries)
    successor = {e.supersedes_id: e.id for e in entries if e.supersedes_id is not None}

    def head(i: int) -> int:
        seen = set()
        while i in successor and i not in seen:
            seen.add(i)
            i = successor[i]
        return i

    current = sorted((e for e in entries if e.id not in successor), key=_order_key)
    known = {e.id for e in entries}
    answers: dict[int, list[DfmEntry]] = {}
    for e in current:
        if e.kind == "answer" and e.reply_to_id in known:
            answers.setdefault(head(e.reply_to_id), []).append(e)

    per_entry: dict[int, dict] = {}
    waiting: list[tuple[int, int, DfmEntry, str]] = []  # (days, position, entry, party)
    for pos, e in enumerate(current):
        answered_by, awaiting = [], []
        if e.kind in DFM_AWAITING_KINDS:
            for p in e.addressed_to or []:
                hits = [a for a in answers.get(e.id, []) if a.party == p]
                if hits:
                    answered_by.extend({"party": p, "entry_id": a.id, "date": _iso(_msg_date(a))} for a in hits)
                else:
                    days = max(0, (today - _msg_date(e)).days)
                    awaiting.append({"party": p, "days": days})
                    waiting.append((days, pos, e, p))
        per_entry[e.id] = {"answered_by": answered_by, "awaiting": awaiting}

    waiting_on = []
    for p in DFM_PARTIES:
        mine = [w[0] for w in waiting if w[3] == p]
        if mine:
            waiting_on.append({"party": p, "count": len(mine), "oldest_days": max(mine)})
    next_step = None
    if waiting:
        days, _, e, p = min(waiting, key=lambda w: (-w[0], w[1]))
        next_step = {"entry_id": e.id, "kind": e.kind, "from": e.party, "to": p, "days": days}
    last = current[-1] if current else None
    last_step = ({"kind": last.kind, "party": last.party, "addressed_to": list(last.addressed_to or []),
                  "date": _iso(_msg_date(last))} if last else None)
    return {
        "current": current, "per_entry": per_entry, "waiting_on": waiting_on, "next_step": next_step,
        "last_step": last_step,
        "all_answered": not waiting and any(e.kind == "answer" for e in current),
    }


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
        await dfm_audit.record_event(session, tool_part_id=tool.id, action="topic_opened", actor_id=user_id,
                                     topic_id=topic.id, details={"title": topic.title})
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
        await dfm_audit.record_event(session, tool_part_id=tool.id, action="topic_closed", actor_id=user_id,
                                     topic_id=topic.id, details={"title": topic.title})
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
        await dfm_audit.record_event(session, tool_part_id=tool.id, action="topic_reopened", actor_id=user_id,
                                     topic_id=topic.id, details={"title": topic.title})
        return topic

    @staticmethod
    async def record_entry(session: AsyncSession, tool: Part, topic: DfmTopic, *, party: str,
                           addressed_to: str | list | None, note: str | None, sent_at: str | None,
                           supersedes_id: int | None, files: list[tuple[str, bytes, str | None]],
                           user_id: int, kind: str | None = None, reply_to_id: int | None = None) -> DfmEntry:
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
        kind = parse_kind(kind)
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
            # an update keeps the kind and reply link of what it updates unless given
            if kind is not None and kind != old.kind:
                raise DfmError("An update keeps the kind of the message it updates")
            kind = old.kind
            if reply_to_id is None:
                reply_to_id = old.reply_to_id
        kind = kind or DFM_KIND_ORIGINAL
        reply_to = await session.get(DfmEntry, reply_to_id) if reply_to_id is not None else None
        check_flow(topic, party, targets, kind, reply_to, reply_to_id)
        for name, contents, _ in files:
            if not (name or "").strip():
                raise DfmError("A file needs a filename")
            if len(contents) > MAX_FILE_SIZE:
                raise DfmError(f"File {name} is over 100MB")

        entry = DfmEntry(topic_id=topic.id, party=party, addressed_to=targets,
                         note=(note or "").strip() or None, sent_at=sent,
                         supersedes_id=supersedes_id, recorded_by=user_id, kind=kind,
                         reply_to_id=reply_to_id)
        session.add(entry)
        await session.flush()

        target_dir = dfm_dir(tool.id, entry.id)
        written: list[str] = []
        stored: list[DfmEntryFile] = []
        try:
            if files:
                os.makedirs(target_dir, exist_ok=True)
            for name, contents, content_type in files:
                ext = os.path.splitext(name)[1].lower()
                saved = f"{uuid.uuid4().hex}{ext}"
                path = os.path.join(target_dir, saved)
                digest = hashlib.sha256()
                with open(path, "wb") as fh:
                    fh.write(contents)
                    digest.update(contents)
                written.append(path)
                stored_type = (content_type or mimetypes.guess_type(name)[0] or "application/octet-stream")
                row = DfmEntryFile(
                    entry_id=entry.id, original_filename=truncate_filename(name), saved_filename=saved,
                    file_size=len(contents),
                    content_type=stored_type[:MAX_CONTENT_TYPE_LEN],
                    sha256=digest.hexdigest(),
                    uploaded_by=user_id)
                session.add(row)
                stored.append(row)
            await session.flush()
            await session.refresh(entry, attribute_names=["files"])
            what = "updated" if supersedes_id else "recorded"
            await ChangelogService.log_action(
                session, part_id=tool.id, action="dfm_entry_recorded",
                action_description=f"DFM entry ({kind}) {what} in {topic.title} by {party} to {', '.join(targets)}"
                                   + (f" with {len(files)} file(s)" if files else ""),
                performed_by=user_id)
            await dfm_audit.record_event(
                session, tool_part_id=tool.id, action="entry_updated" if supersedes_id else "entry_recorded",
                actor_id=user_id, topic_id=topic.id, entry_id=entry.id, details=dfm_audit.entry_details(entry))
            for row in stored:
                await dfm_audit.record_event(
                    session, tool_part_id=tool.id, action="file_attached", actor_id=user_id, topic_id=topic.id,
                    entry_id=entry.id, file_id=row.id, details=dfm_audit.file_details(row))
            await session.flush()
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
    def topic_summary(topic: DfmTopic, today: date | None = None, flow: dict | None = None) -> dict:
        flow = flow or flow_state(topic, today)
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
            "waiting_on": flow["waiting_on"],
            "last_step": flow["last_step"],
            "all_answered": flow["all_answered"],
        }

    @staticmethod
    def file_dict(f: DfmEntryFile, names: dict) -> dict:
        return {
            "id": f.id, "entry_id": f.entry_id, "original_filename": f.original_filename,
            "file_size": f.file_size, "content_type": f.content_type, "sha256": f.sha256,
            "uploaded_by": f.uploaded_by, "uploaded_by_name": names.get(f.uploaded_by),
            "uploaded_at": _iso(f.uploaded_at),
        }

    @staticmethod
    def entry_dict(e: DfmEntry, names: dict, state: dict | None = None) -> dict:
        """state: this entry's answered_by / awaiting from flow_state; earlier
        versions (history) carry empty lists."""
        state = state or {}
        return {
            "id": e.id, "topic_id": e.topic_id, "party": e.party,
            "addressed_to": list(e.addressed_to or []), "note": e.note,
            "kind": e.kind or DFM_KIND_ORIGINAL, "reply_to_id": e.reply_to_id,
            "answered_by": state.get("answered_by", []), "awaiting": state.get("awaiting", []),
            "sent_at": _iso(e.sent_at), "supersedes_id": e.supersedes_id,
            "recorded_by": e.recorded_by, "recorded_by_name": names.get(e.recorded_by),
            "recorded_at": _iso(e.recorded_at),
            "files": [DfmService.file_dict(f, names) for f in e.files],
        }

    @staticmethod
    def topic_detail(topic: DfmTopic, names: dict, today: date | None = None) -> dict:
        """Entries in the order they were received: by sent_at when it is
        set, else the date they were recorded, then recorded_at, then id.
        This lets a backfilled mail dated earlier sit above one recorded
        earlier but sent later. Each supersede chain is collapsed onto its
        newest entry; `history` lists the earlier versions, newest first.
        Adds the derived flow: per entry answered_by / awaiting, per topic
        waiting_on and next_step (the longest waiting addressee)."""
        by_id = {e.id: e for e in topic.entries}
        flow = flow_state(topic, today)
        entries = []
        for e in flow["current"]:
            d = DfmService.entry_dict(e, names, flow["per_entry"][e.id])
            history = []
            cursor = by_id.get(e.supersedes_id) if e.supersedes_id else None
            while cursor is not None:
                history.append(DfmService.entry_dict(cursor, names))
                cursor = by_id.get(cursor.supersedes_id) if cursor.supersedes_id else None
            d["history"] = history
            entries.append(d)
        return {**DfmService.topic_summary(topic, flow=flow), "next_step": flow["next_step"],
                "entries": entries}

    @staticmethod
    def user_ids(topic: DfmTopic) -> set:
        ids = {topic.opened_by, topic.closed_by}
        for e in topic.entries:
            ids.add(e.recorded_by)
            ids.update(f.uploaded_by for f in e.files)
        return ids
