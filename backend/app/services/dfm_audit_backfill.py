"""Backfill of dfm_audit_events from the rows that existed before migration 081.

SQLAlchemy Core only (no ORM models), so it runs the same inside alembic and
in tests on SQLite and PostgreSQL. Idempotent: it does nothing when the audit
table already has events. File views and downloads were never recorded and
cannot be backfilled; reopen history is lost too (only the current close is
known). Every backfilled event carries details.backfilled = true."""
from __future__ import annotations

import sqlalchemy as sa

NOTE_EXCERPT = 120

topics = sa.table(
    "dfm_topics",
    sa.column("id", sa.Integer), sa.column("tool_part_id", sa.Integer), sa.column("title", sa.String),
    sa.column("status", sa.String), sa.column("opened_by", sa.Integer), sa.column("opened_at", sa.DateTime),
    sa.column("closed_by", sa.Integer), sa.column("closed_at", sa.DateTime),
)
entries = sa.table(
    "dfm_entries",
    sa.column("id", sa.Integer), sa.column("topic_id", sa.Integer), sa.column("party", sa.String),
    sa.column("addressed_to", sa.JSON), sa.column("note", sa.Text), sa.column("kind", sa.String),
    sa.column("reply_to_id", sa.Integer), sa.column("supersedes_id", sa.Integer),
    sa.column("recorded_by", sa.Integer), sa.column("recorded_at", sa.DateTime),
)
files = sa.table(
    "dfm_entry_files",
    sa.column("id", sa.Integer), sa.column("entry_id", sa.Integer),
    sa.column("original_filename", sa.String), sa.column("file_size", sa.Integer),
    sa.column("content_type", sa.String), sa.column("uploaded_by", sa.Integer),
    sa.column("uploaded_at", sa.DateTime),
)
events = sa.table(
    "dfm_audit_events",
    sa.column("id", sa.Integer), sa.column("tool_part_id", sa.Integer), sa.column("topic_id", sa.Integer),
    sa.column("entry_id", sa.Integer), sa.column("file_id", sa.Integer), sa.column("action", sa.String),
    sa.column("actor_id", sa.Integer), sa.column("at", sa.DateTime), sa.column("details", sa.JSON),
)

# ties on the same timestamp: topic opened, then entry, then its files, then close
_RANK = {"topic_opened": 0, "entry_recorded": 1, "entry_updated": 1, "file_attached": 2, "topic_closed": 3}


def _excerpt(note):
    if not note:
        return None
    note = " ".join(note.split())
    return note if len(note) <= NOTE_EXCERPT else note[: NOTE_EXCERPT - 3] + "..."


def backfill_dfm_audit(conn: sa.engine.Connection) -> int:
    """Insert events for existing topics, entries and files. Returns the count."""
    if conn.execute(sa.select(sa.func.count()).select_from(events)).scalar():
        return 0
    rows: list[dict] = []

    for t in conn.execute(sa.select(topics)).mappings():
        base = {"tool_part_id": t["tool_part_id"], "topic_id": t["id"], "entry_id": None, "file_id": None}
        rows.append({**base, "action": "topic_opened", "actor_id": t["opened_by"], "at": t["opened_at"],
                     "details": {"title": t["title"], "backfilled": True}, "_src": t["id"]})
        if t["status"] == "finished_confirmed" and t["closed_at"] is not None:
            rows.append({**base, "action": "topic_closed", "actor_id": t["closed_by"] or t["opened_by"],
                         "at": t["closed_at"], "details": {"title": t["title"], "backfilled": True},
                         "_src": t["id"]})

    q = sa.select(entries, topics.c.tool_part_id).join(topics, topics.c.id == entries.c.topic_id)
    for e in conn.execute(q).mappings():
        details = {"kind": e["kind"] or "original", "party": e["party"],
                   "addressed_to": list(e["addressed_to"] or []), "reply_to_id": e["reply_to_id"],
                   "note": _excerpt(e["note"])}
        if e["supersedes_id"] is not None:
            details["supersedes_id"] = e["supersedes_id"]
        details["backfilled"] = True
        rows.append({"tool_part_id": e["tool_part_id"], "topic_id": e["topic_id"], "entry_id": e["id"],
                     "file_id": None, "action": "entry_updated" if e["supersedes_id"] is not None else "entry_recorded",
                     "actor_id": e["recorded_by"], "at": e["recorded_at"], "details": details, "_src": e["id"]})

    q = (sa.select(files, entries.c.topic_id, topics.c.tool_part_id)
         .join(entries, entries.c.id == files.c.entry_id)
         .join(topics, topics.c.id == entries.c.topic_id))
    for f in conn.execute(q).mappings():
        rows.append({"tool_part_id": f["tool_part_id"], "topic_id": f["topic_id"], "entry_id": f["entry_id"],
                     "file_id": f["id"], "action": "file_attached", "actor_id": f["uploaded_by"],
                     "at": f["uploaded_at"],
                     "details": {"filename": f["original_filename"], "size": f["file_size"],
                                 "content_type": f["content_type"], "sha256": None, "backfilled": True},
                     "_src": f["id"]})

    if not rows:
        return 0
    # ids follow time so "newest first by id" holds for backfilled history too
    rows.sort(key=lambda r: (r["at"], _RANK[r["action"]], r["_src"]))
    for r in rows:
        del r["_src"]
    conn.execute(events.insert(), rows)
    return len(rows)
