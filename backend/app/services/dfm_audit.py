"""DFM audit trail: append-only events per tool. record_event only adds to
the session; the caller's commit makes the event part of the change it
describes, so a failed change leaves no event. There is no update or delete."""
from __future__ import annotations

import csv
import io
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dfm import DfmAuditEvent, DfmEntry, DfmEntryFile, DfmTopic, DFM_AUDIT_ACTIONS

NOTE_EXCERPT = 120
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
CSV_COLUMNS = ["at", "actor", "action", "topic", "entry", "file", "details"]


def note_excerpt(note: str | None) -> str | None:
    if not note:
        return None
    note = " ".join(note.split())
    return note if len(note) <= NOTE_EXCERPT else note[: NOTE_EXCERPT - 3] + "..."


def entry_details(entry: DfmEntry) -> dict:
    d = {"kind": entry.kind, "party": entry.party, "addressed_to": list(entry.addressed_to or []),
         "reply_to_id": entry.reply_to_id, "note": note_excerpt(entry.note)}
    if entry.supersedes_id is not None:
        d["supersedes_id"] = entry.supersedes_id
    return d


def file_details(f: DfmEntryFile) -> dict:
    return {"filename": f.original_filename, "size": f.file_size, "content_type": f.content_type,
            "sha256": f.sha256}


async def record_event(session: AsyncSession, *, tool_part_id: int, action: str, actor_id: int,
                       topic_id: int | None = None, entry_id: int | None = None, file_id: int | None = None,
                       details: dict | None = None) -> DfmAuditEvent:
    if action not in DFM_AUDIT_ACTIONS:
        raise ValueError(f"Unknown DFM audit action '{action}'")
    event = DfmAuditEvent(tool_part_id=tool_part_id, topic_id=topic_id, entry_id=entry_id, file_id=file_id,
                          action=action, actor_id=actor_id, details=details or {})
    session.add(event)
    return event


async def list_events(session: AsyncSession, tool_part_id: int, *, topic_id: int | None = None,
                      action: str | None = None, limit: int | None = DEFAULT_LIMIT,
                      before_id: int | None = None) -> list[DfmAuditEvent]:
    """Newest first (by id, which follows insertion order)."""
    q = select(DfmAuditEvent).where(DfmAuditEvent.tool_part_id == tool_part_id)
    if topic_id is not None:
        q = q.where(DfmAuditEvent.topic_id == topic_id)
    if action is not None:
        q = q.where(DfmAuditEvent.action == action)
    if before_id is not None:
        q = q.where(DfmAuditEvent.id < before_id)
    q = q.order_by(DfmAuditEvent.id.desc())
    if limit is not None:
        q = q.limit(limit)
    return list((await session.execute(q)).scalars().all())


async def shape_events(session: AsyncSession, events: list[DfmAuditEvent]) -> list[dict]:
    """Resolve actor, topic, entry and file in one query each."""
    from app.services.dfm_service import user_names

    names = await user_names(session, {e.actor_id for e in events})

    async def fetch(cols, key, ids):
        ids = {i for i in ids if i is not None}
        if not ids:
            return {}
        rows = (await session.execute(select(*cols).where(key.in_(ids)))).all()
        return {r[0]: r for r in rows}

    topics = await fetch((DfmTopic.id, DfmTopic.title), DfmTopic.id, {e.topic_id for e in events})
    entries = await fetch((DfmEntry.id, DfmEntry.kind, DfmEntry.party), DfmEntry.id, {e.entry_id for e in events})
    files = await fetch((DfmEntryFile.id, DfmEntryFile.original_filename), DfmEntryFile.id,
                        {e.file_id for e in events})
    out = []
    for e in events:
        t, en, f = topics.get(e.topic_id), entries.get(e.entry_id), files.get(e.file_id)
        out.append({
            "id": e.id, "at": e.at.isoformat() if e.at else None, "action": e.action,
            "actor": {"id": e.actor_id, "name": names.get(e.actor_id)},
            "topic": {"id": t[0], "title": t[1]} if t else None,
            "entry": {"id": en[0], "kind": en[1], "party": en[2]} if en else None,
            "file": {"id": f[0], "filename": f[1]} if f else None,
            "details": e.details or {},
        })
    return out


def _compact(details: dict) -> str:
    parts = []
    for k, v in (details or {}).items():
        if v is None:
            continue
        if isinstance(v, list):
            v = ",".join(str(x) for x in v)
        elif isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        parts.append(f"{k}={v}")
    return "; ".join(parts)


def to_csv(rows: list[dict]) -> bytes:
    """UTF-8 with BOM so Excel opens umlauts correctly."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        t, en, f = r["topic"], r["entry"], r["file"]
        w.writerow([
            r["at"] or "", r["actor"]["name"] or f"user {r['actor']['id']}", r["action"],
            f"#{t['id']} {t['title']}" if t else "",
            f"#{en['id']} {en['kind']} ({en['party']})" if en else "",
            f"#{f['id']} {f['filename']}" if f else "",
            _compact(r["details"]),
        ])
    return ("﻿" + buf.getvalue()).encode("utf-8")
