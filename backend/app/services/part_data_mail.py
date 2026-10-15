"""Part data mail: new customer data, iterations, files and status changes on a
project's parts go to that project's "part_data" recipient list, as one digest
mail per project, sent as "KTX Apps" through Microsoft Graph (the transport is
TWOS's app/services/notify.py, same Entra app and env names).

Flow:
- ChangelogService.log_action calls enqueue() for every changelog entry. A
  part data / status event on a project with an active list becomes one
  mail_outbox row in the same session (no commit of its own): a rolled-back
  change never mails.
- digest_loop() (started in app.main) runs run_digest() every minute. A
  project whose oldest pending row is NOTIFY_DIGEST_MINUTES old has its
  pending rows claimed (FOR UPDATE SKIP LOCKED, then "sending", committed, so
  a second uvicorn worker cannot pick them too), rendered into one mail, sent,
  and marked sent / failed / skipped. Sends and failures are audited
  (audit_logs, entity_type "project", action "part_data_mail.*").

Nothing in here may raise into a request or the loop.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import Project, User
from app.models.mail import LIST_PART_DATA, MailOutbox, MailRecipient
from app.models.part import Part, PartRelation, PartRevision

log = logging.getLogger(__name__)
_PLANT_TZ = ZoneInfo("America/New_York")

#: Changelog actions that are part data or a status change. Everything else
#: (thumbnails, BOM lines, field comments and flags, material, paint,
#: relations, shrinkage, PPAP, renumbering, deleted files, unchanged customer
#: packages) is noise for this list.
MAIL_EVENTS = frozenset({
    "created",           # customer data received as a new index / new iteration
    "file_uploaded",     # files on a revision (upload, customer package, scripts)
    "promoted",          # our iteration adopted by the customer
    "activated",         # a waiting customer index became the active one
    "rejected",          # iteration rejected / closed
    "status_changed",    # iteration restored
    "intake_decided",    # Development's triage of a new customer index
    "intake_rejected",   # a waiting customer index rejected
    "intake_reopened",   # a rejected customer index restored
    "lifecycle_phase",   # part moved rfq -> nominated -> series (tools: dfm, preseries)
    "metadata_updated",  # only on a brand-new iteration, see _wanted()
})
#: metadata_updated counts only on an iteration created this recently (the
#: summary written right after creating it); later edits are noise.
NEW_ITERATION_WINDOW = timedelta(hours=1)
# A claimed row still "sending" this long after it was queued is a dead send.
STALE_SENDING_MINUTES = 30

#: Plain ASCII addresses only: anything Graph might refuse would fail the whole
#: sendMail, and with it the mail for everyone else on the list (as TWOS).
_EMAIL = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
_BRACKETED = re.compile(r"<([^<>]*)>")


def clean_address(raw: str) -> str:
    """The address inside what people paste: an Outlook To line ("Name <a@b>;"),
    a mailto: link, or a chat message with zero-width characters in it."""
    s = (raw or "").translate(_ZERO_WIDTH).strip()
    m = _BRACKETED.search(s)
    if m:
        s = m.group(1)
    s = s.strip().rstrip(";,.").strip()
    if s.lower().startswith("mailto:"):
        s = s[len("mailto:"):]
    return s.strip().lower()


def valid_address(email: str) -> bool:
    return bool(email) and email.isascii() and bool(_EMAIL.match(email))


# --------------------------------------------------------------------------
# Enqueue (called from ChangelogService.log_action)
# --------------------------------------------------------------------------

async def _has_list(session: AsyncSession, project_id: int) -> bool:
    return (await session.execute(
        select(MailRecipient.id).where(
            MailRecipient.project_id == project_id,
            MailRecipient.list_key == LIST_PART_DATA,
            MailRecipient.active.is_(True)).limit(1))).first() is not None


async def _wanted(session: AsyncSession, action: str, revision_id: Optional[int]) -> bool:
    if action not in MAIL_EVENTS:
        return False
    if action != "metadata_updated":
        return True
    if revision_id is None:
        return False
    rev = await session.get(PartRevision, revision_id)
    if rev is None or rev.parent_revision_id is None or rev.created_at is None:
        return False
    return datetime.utcnow() - rev.created_at <= NEW_ITERATION_WINDOW


async def enqueue(session: AsyncSession, *, part_id: int, action: str, summary: Optional[str],
                  performed_by: Optional[int], revision_id: Optional[int] = None) -> Optional[MailOutbox]:
    """Add an outbox row for a part data / status event when the part's project
    has an active part data list. Same session, no commit."""
    if not await _wanted(session, action, revision_id):
        return None
    project_id = (await session.execute(
        select(Part.project_id).where(Part.id == part_id))).scalar_one_or_none()
    if project_id is None or not await _has_list(session, project_id):
        return None
    row = MailOutbox(project_id=project_id, part_id=part_id, revision_id=revision_id,
                     event=action, summary=summary, performed_by=performed_by,
                     mail_status="pending")
    session.add(row)
    return row


# --------------------------------------------------------------------------
# Transport (ported from TWOS app/services/notify.py)
# --------------------------------------------------------------------------

_token: tuple[str, float] | None = None


def configured() -> bool:
    s = get_settings()
    return bool(s.entra_tenant_id and s.entra_client_id and s.entra_client_secret)


async def _graph_token(client: httpx.AsyncClient) -> str:
    global _token
    if _token and _token[1] > time.time() + 60:
        return _token[0]
    s = get_settings()
    r = await client.post(
        f"https://login.microsoftonline.com/{s.entra_tenant_id}/oauth2/v2.0/token",
        data={"client_id": s.entra_client_id, "client_secret": s.entra_client_secret,
              "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"},
    )
    r.raise_for_status()
    j = r.json()
    _token = (j["access_token"], time.time() + int(j.get("expires_in", 3600)))
    return _token[0]


async def graph_send(to: list[str], subject: str, body: str) -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        token = await _graph_token(client)
        r = await client.post(
            f"https://graph.microsoft.com/v1.0/users/{s.notify_sender}/sendMail",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": {"subject": subject,
                              "body": {"contentType": "Text", "content": body},
                              "toRecipients": [{"emailAddress": {"address": a}} for a in to]},
                  "saveToSentItems": False},
        )
        if r.status_code != 202:
            raise RuntimeError(f"Graph sendMail {r.status_code}: {r.text[:200]}")


def describe_error(exc: Exception) -> str:
    #: httpx timeouts stringify to "", so the type name carries the diagnosis.
    text = str(exc)
    return (f"{type(exc).__name__}: {text}" if text else type(exc).__name__)[:500]


def apply_trial(to: list[str], subject: str, body: str) -> tuple[list[str], str, str, bool]:
    """Trial mode: everything goes only to NOTIFY_TRIAL_RECIPIENT."""
    trial = get_settings().notify_trial_recipient.strip()
    if not trial:
        return to, subject, body, False
    return [trial], f"[TRIAL] {subject}", f"Would have gone to: {', '.join(to)}\n\n{body}", True


def mail_status() -> dict:
    s = get_settings()
    return {"configured": configured(),
            "trial_recipient": s.notify_trial_recipient.strip() or None,
            "sender": s.notify_sender,
            "digest_minutes": s.notify_digest_minutes}


async def send_test(to: str) -> None:
    """One mail to `to` and nobody else (trial setting or not): proves Graph
    works from this server. Raises whatever graph_send raises."""
    s = get_settings()
    trial = s.notify_trial_recipient.strip()
    body = "\n".join([
        "This is a test from PLM2. If you can read it, email from this server works.",
        "",
        f"Sender: {s.notify_sender}",
        f"Mode: trial run. Every part data mail goes only to {trial}." if trial
        else "Mode: live. Part data mails go to each project's part data list.",
        f"Digest: one mail per project, {s.notify_digest_minutes} minutes after the first change.",
    ])
    await graph_send([to], "PLM2 email test", body)


# --------------------------------------------------------------------------
# Digest
# --------------------------------------------------------------------------

def _plant_time(at: datetime) -> str:
    return at.replace(tzinfo=timezone.utc).astimezone(_PLANT_TZ).strftime("%Y-%m-%d %H:%M ET")


def _strip_prefix(name: str, number: Optional[str]) -> str:
    """Names were often imported as "206.881.799 A-Bracket ..."; the number
    is printed in front already."""
    name = (name or "").strip()
    if number and name.startswith(number):
        name = name[len(number):].lstrip(" -–—:/").strip()
    return name


def part_label(part: Part, tools: list[str]) -> str:
    """Customer identity first, internal numbers after:
    "<customer no> / <tier1 no> <name> (KTX <tool no>)"."""
    numbers = [n for n in (part.customer_part_number, part.tier1_part_number) if n]
    name = _strip_prefix(part.name, part.customer_part_number)
    name = _strip_prefix(name, part.tier1_part_number)
    head = " / ".join(numbers) if numbers else part.part_number
    label = f"{head} {name}".strip()
    if tools:
        label += f" (KTX {', '.join(tools)})"
    elif numbers:
        label += f" (KTX {part.part_number})"
    return label


def _status_text(rev: Optional[PartRevision]) -> str:
    if rev is None:
        return ""
    status = getattr(rev.status, "value", rev.status) or ""
    return f"{rev.revision_name} {str(status).replace('_', ' ')}".strip()


async def build_digest(session: AsyncSession, project: Project, rows: list[MailOutbox],
                       list_name: Optional[str] = None) -> tuple[str, str]:
    """One plain text mail for a project's claimed rows. Rows on the same part
    and revision become one line, their summaries joined in order."""
    s = get_settings()
    part_ids = {r.part_id for r in rows}
    parts = {p.id: p for p in (await session.execute(
        select(Part).where(Part.id.in_(part_ids)))).scalars()}
    rev_ids = {r.revision_id for r in rows if r.revision_id}
    revs = {r.id: r for r in (await session.execute(
        select(PartRevision).where(PartRevision.id.in_(rev_ids)))).scalars()} if rev_ids else {}
    user_ids = {r.performed_by for r in rows if r.performed_by}
    users = dict((await session.execute(
        select(User.id, User.full_name).where(User.id.in_(user_ids)))).all()) if user_ids else {}
    # Tools that produce each article: the KTX tool number.
    tools_of: dict[int, list[str]] = {}
    for rel, tool_no in (await session.execute(
            select(PartRelation, Part.part_number)
            .join(Part, Part.id == PartRelation.from_part_id)
            .where(PartRelation.to_part_id.in_(part_ids),
                   PartRelation.relation_type == "produces",
                   Part.item_category == "tool")
            .order_by(Part.part_number))).all():
        tools_of.setdefault(rel.to_part_id, []).append(tool_no)

    groups: "OrderedDict[tuple, list[MailOutbox]]" = OrderedDict()
    for r in sorted(rows, key=lambda r: (r.created_at or datetime.min, r.id)):
        groups.setdefault((r.part_id, r.revision_id), []).append(r)

    lines: list[str] = []
    for (part_id, rev_id), grp in groups.items():
        part = parts.get(part_id)
        if part is None:
            continue
        rev = revs.get(rev_id) if rev_id else None
        summaries: list[str] = []
        for r in grp:
            if r.summary and r.summary not in summaries:
                summaries.append(r.summary)
        status = _status_text(rev)
        head = part_label(part, tools_of.get(part_id, []))
        if part.item_category == "tool":
            head = part_label(part, [])
        line = f"{head} — {status}: " if status else f"{head}: "
        lines.append(line + ("; ".join(summaries) or grp[0].event.replace("_", " ")))
        who = []
        for r in grp:
            n = users.get(r.performed_by)
            if n and n not in who:
                who.append(n)
        last = grp[-1].created_at or datetime.utcnow()
        lines.append(f"  {', '.join(who) or 'PLM2'}, {_plant_time(last)}")
        lines.append(f"  {s.notify_base_url.rstrip('/')}/parts/{part_id}")
        lines.append("")

    n = len(groups)
    proj = f"{project.code} {project.name}".strip()
    all_new_iterations = all(
        any(r.event == "created" for r in grp)
        and (revs.get(rev_id) is not None and revs[rev_id].parent_revision_id is not None)
        for (_, rev_id), grp in groups.items())
    if all_new_iterations:
        what = f"{n} new iteration{'s' if n != 1 else ''}"
    else:
        what = f"{n} part update{'s' if n != 1 else ''}"
    subject = f"PLM2 {proj}: {what}"
    body = "\n".join([subject, ""] + lines + [
        f"You get this as a member of the {list_name or proj} part data list."])
    return subject, body


async def _audit(session: AsyncSession, project_id: int, action: str, payload: dict) -> None:
    from app.services.audit_service import AuditService
    await AuditService.record(session, entity_type="project", entity_id=project_id,
                              action=action, new_values=payload)


async def _claim(session_factory, project_id: int) -> list[int]:
    async with session_factory() as s:
        ids = list((await s.execute(
            select(MailOutbox.id).where(MailOutbox.project_id == project_id,
                                        MailOutbox.mail_status == "pending")
            .order_by(MailOutbox.id)
            .with_for_update(skip_locked=True))).scalars())
        if not ids:
            return []
        for row in (await s.execute(select(MailOutbox).where(MailOutbox.id.in_(ids)))).scalars():
            row.mail_status = "sending"
        await s.commit()
        return ids


async def _finish(session_factory, ids: list[int], status: str, error: Optional[str],
                  project_id: int, audit_action: Optional[str], payload: dict) -> None:
    async with session_factory() as s:
        now = datetime.utcnow()
        for row in (await s.execute(select(MailOutbox).where(MailOutbox.id.in_(ids)))).scalars():
            row.mail_status = status
            row.error = error
            if status == "sent":
                row.sent_at = now
        if audit_action:
            try:
                await _audit(s, project_id, audit_action, payload)
            except Exception:  # noqa: BLE001
                log.exception("part data mail for project %s not audited", project_id)
        await s.commit()


async def send_project(session_factory, project_id: int) -> Optional[str]:
    """Claim, render, send and mark one project's pending rows. Returns the
    final status, or None when another worker had them."""
    ids = await _claim(session_factory, project_id)
    if not ids:
        return None
    subject: Optional[str] = None
    try:
        async with session_factory() as s:
            project = await s.get(Project, project_id)
            rows = list((await s.execute(
                select(MailOutbox).where(MailOutbox.id.in_(ids)))).scalars())
            to = [e for e in (clean_address(e) for e in (await s.execute(
                select(MailRecipient.email).where(
                    MailRecipient.project_id == project_id,
                    MailRecipient.list_key == LIST_PART_DATA,
                    MailRecipient.active.is_(True))
                .order_by(MailRecipient.email))).scalars()) if valid_address(e)]
            if not to:
                log.info("part data mail %s: list is empty, skipped", project_id)
                await _finish(session_factory, ids, "skipped", "no active recipients",
                              project_id, None, {})
                return "skipped"
            if not configured():
                log.info("part data mail %s: Graph not configured, not sent", project_id)
                await _finish(session_factory, ids, "skipped", "Graph not configured (ENTRA_*)",
                              project_id, None, {})
                return "skipped"
            subject, body = await build_digest(s, project, rows)
        actual, subject, body, trial = apply_trial(to, subject, body)
        await graph_send(actual, subject, body)
    except Exception as exc:  # noqa: BLE001: a mail must never break anything
        log.exception("part data mail for project %s failed", project_id)
        err = describe_error(exc)
        await _finish(session_factory, ids, "failed", err, project_id, "part_data_mail.failed",
                      {"subject": subject, "rows": ids, "error": err})
        return "failed"
    # The mail is out: nothing after this point may record it as failed.
    try:
        await _finish(session_factory, ids, "sent", None, project_id, "part_data_mail.sent",
                      {"subject": subject, "to": actual, "trial": trial, "rows": ids})
    except Exception:  # noqa: BLE001
        log.exception("part data mail for project %s sent but not marked", project_id)
    return "sent"


async def run_digest(session_factory=None, now: Optional[datetime] = None) -> dict:
    """Send every project whose oldest pending row is old enough."""
    if session_factory is None:
        from app.models import AsyncSessionLocal
        session_factory = AsyncSessionLocal
    now = now or datetime.utcnow()
    cutoff = now - timedelta(minutes=get_settings().notify_digest_minutes)
    async with session_factory() as s:
        # A worker that died mid-send leaves rows in "sending". Whether that
        # mail went out is unknown, so they end as failed (visible), never
        # back to pending (a resend could double-mail the list).
        stale = (await s.execute(select(MailOutbox).where(
            MailOutbox.mail_status == "sending",
            MailOutbox.created_at <= now - timedelta(minutes=STALE_SENDING_MINUTES)))).scalars().all()
        for row in stale:
            row.mail_status = "failed"
            row.error = "interrupted while sending, delivery unknown"
        if stale:
            await s.commit()
            log.warning("part data mail: %d stale sending rows marked failed", len(stale))
        due = list((await s.execute(
            select(MailOutbox.project_id)
            .where(MailOutbox.mail_status == "pending")
            .group_by(MailOutbox.project_id)
            .having(func.min(MailOutbox.created_at) <= cutoff))).scalars())
    results = {}
    for project_id in due:
        status = await send_project(session_factory, project_id)
        if status:
            results[project_id] = status
    return results


async def digest_loop(interval_s: float = 60.0) -> None:
    while True:
        try:
            await run_digest()
        except Exception as e:  # noqa: BLE001
            log.warning("Part data mail digest failed: %s", e)
        await asyncio.sleep(interval_s)
