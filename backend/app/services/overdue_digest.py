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
Cut 2 (migration 149, Christoph 2026-10-26): each department's manager
(wf_departments.manager_id) reads the late items of the departments they
manage; the configured recipients keep the rest (items no one department
owes, departments without an active manager). The same late items feed
the managers' "Late in my departments" group in My Tasks
(late_in_departments). The per-change
digest for the people involved in a change is app/services/change_digest.py
(same late items, late_by_change)."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

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

#: The stage rows the digest watches (spec §0: "Sales tasks: Sales +
#: Christoph's digest"), by the status that makes them owed. D2: the
#: hand-over (captured) is the lead's, the quote and the answer Sales'.
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


async def managed_department_ids(session: AsyncSession) -> dict[int, int]:
    """{department id: manager id} for the active departments whose manager
    is an active user (migration 149). A department without one, or whose
    manager left, falls back to the configured recipients."""
    return dict((await session.execute(
        select(Department.id, Department.manager_id)
        .join(User, User.id == Department.manager_id)
        .where(Department.is_active.is_(True), User.is_active.is_(True)))).all())


async def overdue_lines(session: AsyncSession, now: Optional[datetime] = None,
                        viewer: Optional[User] = None,
                        keep: Optional[Callable[[Optional[int]], bool]] = None
                        ) -> list[str]:
    """One line per change with everything late on it, oldest change first;
    only the viewer's organization's changes when a viewer is given. keep:
    which owning department ids to list (None = everything; the item's
    department_id is None when no one department owes it)."""
    from app.services.cm_labels import label
    now = now or datetime.utcnow()
    changes = await _open_changes(session, viewer)
    if not changes:
        return []
    items: dict[int, list[str]] = {}
    for e in await late_entries(session, changes, now):
        if keep is None or keep(e["department_id"]):
            items.setdefault(e["change_id"], []).append(e["text"])
    out = []
    for cid in sorted(items, key=lambda i: changes[i].change_number):
        c = changes[cid]
        lead = f", lead {c.lead_name}" if getattr(c, "lead_name", None) else ""
        out.append(f"{c.change_number} ({label('status', c.status)}{lead}): "
                   + "; ".join(items[cid]))
    return out


async def _open_changes(session: AsyncSession, viewer: Optional[User]) -> dict:
    from app.services.change_service import _org_scope
    return {c.id: c for c in (await session.execute(_org_scope(select(ChangeRequest).where(
        ChangeRequest.status.not_in(TERMINAL_STATUSES)), viewer))).scalars().all()}


async def late_by_change(session: AsyncSession, changes: dict,
                         now: datetime, *, deadlines: bool = True) -> dict[int, list[str]]:
    """What is late on each of these changes ({id: change}), in words: one
    list per change with anything late (the digests' shared source).
    deadlines: list a passed deadline too (the change digest names the
    deadline on its own)."""
    items: dict[int, list[str]] = {}
    for e in await late_entries(session, changes, now, deadlines=deadlines):
        items.setdefault(e["change_id"], []).append(e["text"])
    return items


async def late_entries(session: AsyncSession, changes: dict, now: datetime, *,
                       deadlines: bool = True) -> list[dict]:
    """Everything late on these changes ({id: change}), one entry per item:
    {change_id, kind, department_id, department, label, owner_name, due,
    text}. department_id is the department that owes it (assessment, task,
    costing input, sign-off side, Project Management for the internal
    approval and a leadless hand-over, Sales for its stage rows); None when
    no one department does (a lead's hand-over, an override, a deadline).
    The digests (late_by_change, overdue_lines) and the managers' "Late in
    my departments" group (late_in_departments) read it, so they agree."""
    from app.services.notification_sweep import escalated
    out: list[dict] = []
    if not changes:
        return out

    await due_rules.load_clock_floor(session)
    names = dict((await session.execute(select(Department.id, Department.name))).all())
    by_name = {n: i for i, n in names.items()}

    def add(cid: int, kind: str, dept_id: Optional[int], lbl: str,
            owner: Optional[str], due: Optional[datetime], text: str) -> None:
        out.append({"change_id": cid, "kind": kind, "department_id": dept_id,
                    "department": names.get(dept_id) if dept_id else None,
                    "label": lbl, "owner_name": owner, "due": due, "text": text})

    from app.services.project_team_service import _responsible
    resp_cache: dict = {}

    async def responsible_name(cid, dept_id) -> Optional[str]:
        """esc P2-3: an unclaimed row names the department's project-team
        responsible (else its backup), who owns it."""
        c = changes.get(cid)
        key = (getattr(c, "project_id", None), dept_id)
        if key not in resp_cache:
            r = await _responsible(session, key[0], dept_id)
            resp_cache[key] = r[1] if r else None
        return resp_cache[key]

    for a in (await session.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id.in_(changes),
            ChangeAssessment.status == "active",
            ChangeAssessment.wf_instance_task_id.is_(None),
            ChangeAssessment.due_date.is_not(None),
            ChangeAssessment.due_date < now))).scalars().all():
        if not escalated(a.due_date, now):
            continue
        dept = names.get(a.department_id, 'a department')
        owner = a.owner_name or await responsible_name(a.change_id, a.department_id)
        who = f", {owner}" if owner else ""
        add(a.change_id, "assessment", a.department_id, f"{dept} assessment",
            owner, a.due_date,
            f"{dept} assessment{who} (due {fmt_date(a.due_date)})")
    from app.services.notification_sweep import change_task_query
    q, change_of = change_task_query()
    for t, cid in (await session.execute(
            q.where(change_of.in_(list(changes)),
                    WfInstanceTask.due_date < now))).all():
        if not escalated(t.due_date, now):
            continue
        dept = names.get(t.department_id, 'a department')
        owner = (t.owner_name if t.owner_id is not None and t.owner_name
                 else await responsible_name(cid, t.department_id))
        who = f", {owner}" if owner else ""
        add(cid, "wf_task", t.department_id, f"{dept} task", owner, t.due_date,
            f"{dept}{who} (due {fmt_date(t.due_date)})")

    from app.services.owed_items import late_items, owed_items
    for i in late_items(await owed_items(session, list(changes.values()), now,
                                         with_owners=False), now):
        add(i["change"].id, i["kind"], i.get("department_id"), i["label"],
            i["owner"], i["due"],
            f"{i['label']} ({i['owner']}, due {fmt_date(i['due'])})")

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
        # A6-01: the one start rule, task clock floor included
        start = due_rules.start_of("sales", None, since.get(c.id), c.created_at, now)
        due = (due_rules.add_wd(start, due_rules.CUSTOMER_CONTACT_WD)
               if c.status == "quoted" else due_rules.task_due(start, c, "sales"))
        if due_rules.is_late(due, now):
            if c.status == "captured":
                # D2: the hand-over is the lead's (no lead: Project Management)
                if getattr(c, "lead_name", None):
                    who, owner, dept_id = f"Lead {c.lead_name}", c.lead_name, None
                else:
                    who = owner = "Project Management"
                    dept_id = by_name.get("Project Manager")
            else:
                owner = c.sales_owner_name if c.sales_owner_id else None
                who = "Sales" + (f" ({owner})" if owner else "")
                dept_id = by_name.get("Sales")
            add(c.id, "stage", dept_id, what[:1].upper() + what[1:], owner or who,
                due, f"{who}: {what} (due {fmt_date(due)})")

    # Christoph 2026-11-02: a hold nobody looked at 3 working days after its
    # review date is Project Management's (its manager reads it)
    from app.services import hold_review
    for c in changes.values():
        if hold_review.escalated(c, now):
            owner = getattr(c, "lead_name", None) or "Project Management"
            due = hold_review.due_at(c.hold_review_date)
            add(c.id, "hold_review", by_name.get("Project Manager"),
                "Hold review", owner, due,
                f"On hold, review date {fmt_date(c.hold_review_date)} passed "
                f"({owner}: resume, cancel or set a new date)")

    for c in changes.values() if deadlines else ():
        kind = c.active_deadline
        due = (c.release_due_date if kind == "release"
               else c.required_by_date if kind == "quote" else None)
        if due is not None and due < now:
            word = 'release' if kind == 'release' else 'quote'
            add(c.id, "deadline", None, f"{word.capitalize()} deadline", None, due,
                f"{word} deadline passed {fmt_date(due)}")
    return out


async def late_in_departments(session: AsyncSession, department_ids,
                              viewer: Optional[User] = None,
                              now: Optional[datetime] = None) -> list[dict]:
    """My Tasks' "Late in my departments" (migration 149): every escalated
    item these departments owe, across all open changes of the viewer's
    organization, one row each, most days late first. Read-only rows: the
    manager is told, not given the task."""
    wanted = set(department_ids)
    if not wanted:
        return []
    now = now or datetime.utcnow()
    changes = await _open_changes(session, viewer)
    rows = []
    for e in await late_entries(session, changes, now, deadlines=False):
        if e["department_id"] not in wanted:
            continue
        c = changes[e["change_id"]]
        rows.append({
            "kind": e["kind"], "change_id": c.id, "change_number": c.change_number,
            "change_title": c.title, "department_id": e["department_id"],
            "department_name": e["department"], "label": e["label"],
            "owner_name": e["owner_name"],
            "due_date": e["due"].isoformat() if e["due"] else None,
            "days_overdue": (now - e["due"]).days if e["due"] else 0,
        })
    rows.sort(key=lambda r: (-r["days_overdue"], r["change_number"], r["label"]))
    return rows


async def send_overdue_digest(session: AsyncSession,
                              now: Optional[datetime] = None) -> int:
    """Today's digest to every recipient who has none yet. Returns how many
    were created. Cut 2 (migration 149): a department's manager reads the
    late items of the departments they manage; the configured recipients
    read the rest (no one department, or a department without an active
    manager). One digest per person and day, both parts in it."""
    if not cm_switches.on("RELEASE_V2"):
        return 0
    now = now or datetime.utcnow()
    managed = await managed_department_ids(session)
    fallback = {u.id: u for u in await digest_recipients(session)}
    mine: dict[int, set[int]] = {}
    for dept_id, uid in managed.items():
        mine.setdefault(uid, set()).add(dept_id)
    users = dict(fallback)
    if mine:
        users.update({u.id: u for u in (await session.execute(
            select(User).where(User.id.in_(list(mine))))).scalars().all()})
    if not users:
        return 0
    # esc P3-1: the digest day is the business day (Toccoa), not the UTC
    # date: two digests on one local evening otherwise
    from app.utils.clock import business_date_of
    key = f"digest:{business_date_of(now).isoformat()}"
    had = set((await session.execute(select(Notification.user_id).where(
        Notification.kind == DIGEST_KIND, Notification.subject_key == key,
        Notification.user_id.in_(list(users))))).scalars().all())
    todo = [u for uid, u in sorted(users.items()) if uid not in had]
    if not todo:
        return 0
    from app.services.notification_service import NotificationService
    sent = 0
    for u in todo:
        depts = mine.get(u.id, set())
        rest = u.id in fallback

        def keep(dept_id, depts=depts, rest=rest) -> bool:
            if dept_id is not None and dept_id in depts:
                return True
            return rest and (dept_id is None or dept_id not in managed)
        lines = await overdue_lines(
            session, now, viewer=None if u.effective_role == "admin" else u, keep=keep)
        if not lines:
            continue
        sent += await NotificationService.notify_once(
            session, [u.id], kind=DIGEST_KIND, subject_key=key, include_read=True,
            title=f"Overdue today: {len(lines)} change(s)",
            body="\n".join(lines), link="/changes")
    return sent
