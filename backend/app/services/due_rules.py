"""Due dates and lateness of change work (ECR-solid C20, spec §0).

Two due rules, one escalation rule, all in working days (Mon-Fri):

- Task: 2 wd from when it became owed; 1 wd when the change is urgent
  (priority 'critical') or others wait on it (FAST_KINDS).
- Assessment: min(now + 7 d, deadline - 3 wd), deadline = the quote deadline
  or the need-by date, whichever is earlier; floor 2 wd (urgent 1 wd).
- Late at due + 1 wd: the item then shows to the owner's department, in the
  lead's "Overdue" group and in the overdue digest.

With ASSESSMENT_V2 off the assessment due is the old flat 7 days and task
rows keep the change's deadline as their due date (callers check on())."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.services import cm_switches

TASK_WD = 2
FAST_TASK_WD = 1
ASSESSMENT_DAYS = 7
ASSESSMENT_BEFORE_DEADLINE_WD = 3
ASSESSMENT_FLOOR_WD = 2
URGENT_FLOOR_WD = 1
LATE_AFTER_WD = 1

#: Task kinds others wait on (spec §0): revision triage, the new-index
#: decision, ppap_decision, the customer flip. Due in 1 wd.
FAST_KINDS = frozenset({"revision_triage", "index_decision", "ppap_decision",
                        "customer_flip"})


def _step(d: datetime, n: int, sign: int) -> datetime:
    if not isinstance(n, int) or n < 0:
        raise TypeError("working days must be a non-negative int")
    while n:
        d += timedelta(days=sign)
        if d.weekday() < 5:
            n -= 1
    return d


def add_wd(d: datetime, n: int) -> datetime:
    """`d` plus n working days (Mon-Fri), time of day kept."""
    return _step(d, n, 1)


def sub_wd(d: datetime, n: int) -> datetime:
    """`d` minus n working days (Mon-Fri), time of day kept."""
    return _step(d, n, -1)


def is_urgent(change) -> bool:
    return getattr(change, "priority", None) == "critical"


def deadline_of(change) -> tuple[Optional[datetime], Optional[str]]:
    """(date, 'quote' | 'need_by') the work runs against: the quote deadline
    until the offer went out, the need-by (release) date; the earlier of the
    two when both are set. (None, None) when neither is."""
    out: list[tuple[datetime, str]] = []
    quote = getattr(change, "required_by_date", None)
    if quote is not None and getattr(change, "quoted_at", None) is None:
        out.append((quote, "quote"))
    need_by = getattr(change, "release_due_date", None)
    if need_by is not None:
        out.append((need_by, "need_by"))
    if not out:
        return None, None
    return min(out, key=lambda x: x[0])


def task_due(since: datetime, change, kind: str) -> datetime:
    """Due date of a task that became owed at `since`."""
    n = FAST_TASK_WD if (is_urgent(change) or kind in FAST_KINDS) else TASK_WD
    return add_wd(since, n)


def assessment_due(change, now: Optional[datetime] = None) -> datetime:
    """Due date of a department's assessment that opens now."""
    now = now or datetime.utcnow()
    if not cm_switches.on("ASSESSMENT_V2"):
        return now + timedelta(days=ASSESSMENT_DAYS)
    due = now + timedelta(days=ASSESSMENT_DAYS)
    dl, _ = deadline_of(change)
    if dl is not None:
        due = min(due, sub_wd(dl, ASSESSMENT_BEFORE_DEADLINE_WD))
    floor = add_wd(now, URGENT_FLOOR_WD if is_urgent(change) else ASSESSMENT_FLOOR_WD)
    return max(due, floor)


def late_at(due: datetime) -> datetime:
    return add_wd(due, LATE_AFTER_WD)


def is_late(due: Optional[datetime], now: Optional[datetime] = None) -> bool:
    """Past due + 1 wd: escalated to the department, the lead and the digest."""
    if due is None:
        return False
    return (now or datetime.utcnow()) >= late_at(due)


async def apply_assessment_due(session, change) -> int:
    """Entering assessment: every department's open assessment (its engine
    task, or the row itself when it has none) is due by the assessment rule
    instead of the engine's flat default. Returns how many were set."""
    if not cm_switches.on("ASSESSMENT_V2"):
        return 0
    from sqlalchemy import select
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    due = assessment_due(change)
    tasks = (await session.execute(
        select(WfInstanceTask).join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
        .where(WfInstance.change_id == change.id, WfInstance.status == "active",
               WfInstanceTask.status == "active",
               WfInstanceTask.is_actionable.is_(True)))).scalars().all()
    rows = (await session.execute(
        select(ChangeAssessment).where(
            ChangeAssessment.change_id == change.id,
            ChangeAssessment.status == "active",
            ChangeAssessment.wf_instance_task_id.is_(None)))).scalars().all()
    for x in (*tasks, *rows):
        x.due_date = due
    if tasks or rows:
        await session.flush()
    return len(tasks) + len(rows)


#: My Tasks "Needs you" (spec §0): decisions only this person can give.
NEEDS_YOU_KINDS = frozenset({"deviation_decision", "sign_off", "internal_approval",
                             "ppap_decision"})
#: A customer wait is due at the next contact date (C4 default: +5 wd).
CUSTOMER_CONTACT_WD = 5
#: Rows that bring their own due date (the assessment's, the validation
#: issue engine's): the task rule leaves them alone.
OWN_DUE_PREFIXES = ("assessment", "validation_issue_")


def needs_you(task: dict) -> bool:
    return (bool(task.get("needs_you")) or task["kind"] in NEEDS_YOU_KINDS
            or (task["kind"] == "validation_issue_customer"
                and bool(task.get("concession"))))


async def annotate_tasks(session, tasks: list[dict], changes,
                         now: Optional[datetime] = None) -> None:
    """Give every My Tasks row its due date by the two rules, the deadline
    it runs against ("due Thu (quote deadline Mon)"), urgent, overdue, late
    (due + 1 wd) and needs_you. A row's start is its own `since` (the
    question asked, the override proposed, the customer's yes), else when
    the change entered its status, else its creation."""
    now = now or datetime.utcnow()
    on = cm_switches.on("ASSESSMENT_V2")
    by_id = {c.id: c for c in changes}
    since: dict = {}
    ids = list({t["change_id"] for t in tasks if t["change_id"] in by_id})
    if on and ids:
        from sqlalchemy import func, select
        from app.models.change import ChangeChangelog
        since = dict((await session.execute(
            select(ChangeChangelog.change_id, func.max(ChangeChangelog.performed_at))
            .where(ChangeChangelog.change_id.in_(ids),
                   ChangeChangelog.field_name == "status")
            .group_by(ChangeChangelog.change_id))).all())
    for t in tasks:
        t["needs_you"] = needs_you(t)
        start = t.pop("since", None)
        c = by_id.get(t["change_id"])
        if not on or c is None:
            t.setdefault("late", False)
            continue
        dl, dl_kind = deadline_of(c)
        t["deadline_date"], t["deadline_kind"] = dl, dl_kind
        t["urgent"] = is_urgent(c)
        if t["kind"].startswith(OWN_DUE_PREFIXES):
            due = t.get("due_date")
        else:
            start = start or since.get(c.id) or c.created_at or now
            due = (add_wd(start, CUSTOMER_CONTACT_WD) if t["kind"] == "customer_response"
                   else task_due(start, c, t["kind"]))
            t["due_date"] = due
            t["overdue"] = due < now
        t["late"] = is_late(due, now) if isinstance(due, datetime) else False


def task_order(t: dict) -> tuple:
    """One order for the list: main before backup; "Needs you" on top, by
    due; then mine, overdue, soonest due (undated last), change number."""
    due = t.get("due_date")
    due_key = (due is None, due or datetime.max)
    if t.get("needs_you"):
        return (t.get("role") == "backup", 0, *due_key, t["change_number"])
    return (t.get("role") == "backup", 1, not t.get("mine", False),
            not t["overdue"], *due_key, t["change_number"])
