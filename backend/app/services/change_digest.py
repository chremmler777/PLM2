"""The daily digest for the people involved in a change (ECR-solid spec §0
Notifications "Digest: one line per change (phase, answers, deadline,
waits, overdue)", §4 "raiser and lead's digest told"; switch RELEASE_V2).

Once a day each lead, raiser and Sales owner of a live change gets one
notification (kind change_digest, mailed) with one line per change of
theirs that has news or needs an eye:
  "CR-2026-0006 (In assessment): quote deadline 28 Oct (at risk);
   2 answered, 1 closed since yesterday; waiting on 1 answer;
   late: Tool Engineer assessment (due 12 Oct)".
A change with nothing to tell (no new answers, deadline on track, no
wait, nothing late) has no line; nobody with no line gets a digest.
Read-only and inactive accounts get none (nothing they could act on).
Late items are the overdue digest's own (overdue_digest.late_by_change),
so the managers' digest, this one, the lead's "Overdue" group and the
Late chips agree. Supplier waits join with the supplier wait (lane L5)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.display import fmt_date
from app.models.change import TERMINAL_STATUSES, ChangeRequest
from app.models.entities import User
from app.models.notification import Notification
from app.services import cm_switches

DIGEST_KIND = "change_digest"
WINDOW = timedelta(days=1)


async def change_lines(session: AsyncSession, changes: list,
                       now: datetime) -> dict[int, str]:
    """{change id: its digest line} for the changes with something to tell."""
    from app.services.change_service import ChangeService
    from app.services.cm_labels import label
    from app.services.overdue_digest import late_by_change
    late = await late_by_change(session, {c.id: c for c in changes}, now,
                                deadlines=False)
    out: dict[int, str] = {}
    since = now - WINDOW
    for c in changes:
        news = []
        answered = sum(1 for q in c.concerns if q.kind == "needs_info"
                       and q.answered_at is not None and q.answered_at >= since)
        closed = sum(1 for q in c.concerns if q.kind != "risk"
                     and q.withdrawn_at is not None and q.withdrawn_at >= since)
        if answered:
            news.append(f"{answered} answered")
        if closed:
            news.append(f"{closed} closed")
        waits = []
        open_q = ChangeService.unanswered_questions(c)
        if open_q:
            waits.append(f"waiting on {len(open_q)} answer{'s' if len(open_q) > 1 else ''}")
        if c.status == "quoted" and c.customer_response in (None, "pending"):
            waits.append("waiting on the customer"
                         + (f" since {fmt_date(c.quoted_at)}" if c.quoted_at else ""))
        kind = c.active_deadline
        state = await ChangeService.deadline_state(session, c) if kind else None
        alarm = state in ("at_risk", "overdue")
        if not (news or waits or late.get(c.id) or alarm):
            continue        # nothing to tell about this change today
        parts = []
        if kind:
            due = c.release_due_date if kind == "release" else c.required_by_date
            parts.append(f"{'release' if kind == 'release' else 'quote'} deadline "
                         f"{fmt_date(due)}"
                         + (f" ({state.replace('_', ' ')})" if alarm else ""))
        if news:
            parts.append(", ".join(news) + " since yesterday")
        parts += waits
        if late.get(c.id):
            parts.append("late: " + "; ".join(late[c.id]))
        out[c.id] = (f"{c.change_number} ({label('status', c.status)}): "
                     + "; ".join(parts))
    return out


async def send_change_digest(session: AsyncSession,
                             now: Optional[datetime] = None) -> int:
    """Today's digest to every involved person who has none yet. Returns how
    many were created."""
    if not cm_switches.on("RELEASE_V2"):
        return 0
    now = now or datetime.utcnow()
    changes = (await session.execute(select(ChangeRequest).where(
        ChangeRequest.status.not_in(TERMINAL_STATUSES)))).scalars().all()
    involved: dict[int, list] = {}
    for c in changes:
        for uid in {c.lead_id, c.raised_by, c.sales_owner_id} - {None}:
            involved.setdefault(uid, []).append(c)
    if not involved:
        return 0
    key = f"change-digest:{now.date().isoformat()}"
    had = set((await session.execute(select(Notification.user_id).where(
        Notification.kind == DIGEST_KIND, Notification.subject_key == key,
        Notification.user_id.in_(list(involved))))).scalars().all())
    users = (await session.execute(select(User).where(
        User.id.in_([u for u in involved if u not in had]),
        User.is_active.is_(True)))).scalars().all()
    from app.services.change_service import ChangeService
    users = await ChangeService._writers(session, list(users))
    if not users:
        return 0
    lines = await change_lines(
        session, list({c.id: c for u in users for c in involved[u.id]}.values()), now)
    from app.services.notification_service import NotificationService
    sent = 0
    for u in users:
        mine = [lines[c.id] for c in sorted(involved[u.id], key=lambda c: c.change_number)
                if c.id in lines]
        if not mine:
            continue
        sent += await NotificationService.notify_once(
            session, [u.id], kind=DIGEST_KIND, subject_key=key, include_read=True,
            title=f"Your changes today: {len(mine)} with news",
            body="\n".join(mine), link="/my-tasks")
    return sent
