"""The daily overdue digest (ECR-solid C27, spec §0 P6, switch RELEASE_V2).

Cut 1: one notification a day to the configured managers
(settings.overdue_digest_recipients; Christoph by default), one line per
change with what is late: department assessments and change tasks past
due + 1 working day, the computed rows that owe a number or a decision
(owed_items: costing input, sign-offs, internal approval, overrides),
Sales' stage tasks (hand-over, quote, customer answer) by the task rule,
and overdue change deadlines. Nothing
late, no digest. Sent at most once per recipient and day, read or not.
Lateness is the sweep's own test (notification_sweep.escalated). Each
recipient sees only the changes of their organization (change_service
_org_scope; admins see all), so a non-admin deputy never reads other
organizations' titles, leads or owners.
Cut 2 replaces the list with a manager per department. The per-change
digest for the people involved in a change is app/services/change_digest.py
(same late items, late_by_change)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.display import fmt_date
from app.models.change import (
    TERMINAL_STATUSES, ChangeAssessment, ChangeChangelog, ChangeRequest,
)
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, WfInstance, WfInstanceTask
from app.services import cm_switches, due_rules

DIGEST_KIND = "overdue_digest"

#: Sales' stage rows the digest watches (spec §0: "Sales tasks: Sales +
#: Christoph's digest"), by the status that makes them owed.
SALES_ROWS = {"captured": "hand over to scoping", "quoting": "create the quote",
              "quoted": "record the customer answer"}


async def digest_recipients(session: AsyncSession) -> list[User]:
    from app.core.config import get_settings
    wanted = {x.strip().lower() for x in
              (get_settings().overdue_digest_recipients or "").split(",") if x.strip()}
    if not wanted:
        return []
    return list((await session.execute(select(User).where(
        User.is_active.is_(True),
        func.lower(User.username).in_(wanted) | func.lower(User.email).in_(wanted)
    ))).scalars().all())


async def overdue_lines(session: AsyncSession, now: Optional[datetime] = None,
                        viewer: Optional[User] = None) -> list[str]:
    """One line per change with everything late on it, oldest change first;
    only the viewer's organization's changes when a viewer is given."""
    from app.services.change_service import _org_scope
    now = now or datetime.utcnow()
    changes = {c.id: c for c in (await session.execute(_org_scope(select(ChangeRequest).where(
        ChangeRequest.status.not_in(TERMINAL_STATUSES)), viewer))).scalars().all()}
    if not changes:
        return []
    items = await late_by_change(session, changes, now)
    out = []
    for cid in sorted(items, key=lambda i: changes[i].change_number):
        c = changes[cid]
        lead = f", lead {c.lead_name}" if getattr(c, "lead_name", None) else ""
        out.append(f"{c.change_number} ({c.status}{lead}): " + "; ".join(items[cid]))
    return out


async def late_by_change(session: AsyncSession, changes: dict,
                         now: datetime, *, deadlines: bool = True) -> dict[int, list[str]]:
    """What is late on each of these changes ({id: change}), in words: one
    list per change with anything late (the digests' shared source).
    deadlines: list a passed deadline too (the change digest names the
    deadline on its own)."""
    from app.services.notification_sweep import escalated
    items: dict[int, list[str]] = {}
    if not changes:
        return items

    def add(cid: int, text: str) -> None:
        items.setdefault(cid, []).append(text)

    names = dict((await session.execute(select(Department.id, Department.name))).all())
    for a in (await session.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id.in_(changes),
            ChangeAssessment.status == "active",
            ChangeAssessment.wf_instance_task_id.is_(None),
            ChangeAssessment.due_date.is_not(None),
            ChangeAssessment.due_date < now))).scalars().all():
        if not escalated(a.due_date, now):
            continue
        add(a.change_id, f"{names.get(a.department_id, 'a department')} assessment "
                         f"(due {fmt_date(a.due_date)})")
    from app.services.notification_sweep import change_task_query
    q, change_of = change_task_query()
    for t, cid in (await session.execute(
            q.where(change_of.in_(list(changes)),
                    WfInstanceTask.due_date < now))).all():
        if not escalated(t.due_date, now):
            continue
        who = f", {t.owner_name}" if t.owner_id is not None and t.owner_name else ""
        add(cid, f"{names.get(t.department_id, 'a department')}{who} "
                 f"(due {fmt_date(t.due_date)})")

    from app.services.owed_items import late_items, owed_items
    for i in late_items(await owed_items(session, list(changes.values()), now,
                                         with_owners=False), now):
        add(i["change"].id, f"{i['label']} ({i['owner']}, due {fmt_date(i['due'])})")

    since = dict((await session.execute(
        select(ChangeChangelog.change_id, func.max(ChangeChangelog.performed_at))
        .where(ChangeChangelog.change_id.in_(changes),
               ChangeChangelog.field_name == "status")
        .group_by(ChangeChangelog.change_id))).all())
    for c in changes.values():
        if not c.customer_relevant:
            continue
        what = SALES_ROWS.get(c.status)
        if c.status == "quoted" and c.customer_response not in (None, "pending"):
            what = None
        if what is None:
            continue
        start = since.get(c.id) or c.created_at
        due = (due_rules.add_wd(start, due_rules.CUSTOMER_CONTACT_WD)
               if c.status == "quoted" else due_rules.task_due(start, c, "sales"))
        if due_rules.is_late(due, now):
            owner = f" ({c.sales_owner_name})" if c.sales_owner_id else ""
            add(c.id, f"Sales{owner}: {what} (due {fmt_date(due)})")

    for c in changes.values() if deadlines else ():
        kind = c.active_deadline
        due = (c.release_due_date if kind == "release"
               else c.required_by_date if kind == "quote" else None)
        if due is not None and due < now:
            add(c.id, f"{'release' if kind == 'release' else 'quote'} deadline "
                      f"passed {fmt_date(due)}")
    return items


async def send_overdue_digest(session: AsyncSession,
                              now: Optional[datetime] = None) -> int:
    """Today's digest to every recipient who has none yet. Returns how many
    were created."""
    if not cm_switches.on("RELEASE_V2"):
        return 0
    now = now or datetime.utcnow()
    users = await digest_recipients(session)
    if not users:
        return 0
    key = f"digest:{now.date().isoformat()}"
    had = set((await session.execute(select(Notification.user_id).where(
        Notification.kind == DIGEST_KIND, Notification.subject_key == key,
        Notification.user_id.in_([u.id for u in users])))).scalars().all())
    todo = [u for u in users if u.id not in had]
    if not todo:
        return 0
    from app.services.notification_service import NotificationService
    sent = 0
    unscoped: Optional[list[str]] = None
    for u in todo:
        if u.effective_role == "admin":
            if unscoped is None:
                unscoped = await overdue_lines(session, now)
            lines = unscoped
        else:
            lines = await overdue_lines(session, now, viewer=u)
        if not lines:
            continue
        sent += await NotificationService.notify_once(
            session, [u.id], kind=DIGEST_KIND, subject_key=key, include_read=True,
            title=f"Overdue today: {len(lines)} change(s)",
            body="\n".join(lines), link="/changes")
    return sent
