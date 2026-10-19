"""Due dates and lateness of change work (ECR-solid C20, spec §0).

Two due rules, one escalation rule, all in working days (Mon-Fri):

- Task: 2 wd from when it became owed; 1 wd when the change is urgent
  (priority 'critical') or others wait on it (FAST_KINDS).
- Assessment: min(now + 7 d, deadline - 3 wd), deadline = the quote deadline
  or the need-by date, whichever is earlier; floor 2 wd (urgent 1 wd).
- Late at due + 1 wd: department assessments, engine tasks and the
  computed rows that owe a number or a decision (costing input, sign-offs,
  internal approval, overrides) then show in the lead's "Overdue" group and
  the overdue digest, Sales' stage rows in the digest (escalation_of);
  other rows are flagged Late for their owner.

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
    (customer changes only, until the offer went out, as
    ChangeRequest.active_deadline counts it), the need-by (release) date;
    the EARLIER of the two when both are set, deliberately unlike
    active_deadline (release first): a due date must meet both promises,
    the header shows the phase's one. (None, None) when neither is."""
    out: list[tuple[datetime, str]] = []
    quote = getattr(change, "required_by_date", None)
    if (quote is not None and getattr(change, "customer_relevant", False)
            and getattr(change, "quoted_at", None) is None):
        out.append((quote, "quote"))
    need_by = getattr(change, "release_due_date", None)
    if need_by is not None:
        out.append((need_by, "need_by"))
    if not out:
        return None, None
    return min(out, key=lambda x: x[0])


#: org_settings key migration 145 stamps with its run time (the go-live of
#: the task clock); the earliest stamp of any organization counts.
CLOCK_SETTING_KEY = "cm_task_clock_from"
_stamped_floor: Optional[datetime] = None


def _parse(raw: Optional[str]) -> Optional[datetime]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def load_clock_floor(session) -> Optional[datetime]:
    """Read the stamped go-live (org_settings, written by migration 145)
    so clock_floor() serves it; every entry point that dates computed rows
    (annotate_tasks, owed_items, the digests) calls this first. A6-01: a
    safe default, so changes in flight at go-live are not all Late on the
    first sweep even when CM_TASK_CLOCK_FROM is not set."""
    global _stamped_floor
    from sqlalchemy import select
    from app.models.cost_sheet import OrgSetting
    vals = (await session.execute(select(OrgSetting.value).where(
        OrgSetting.key == CLOCK_SETTING_KEY))).scalars().all()
    stamps = [d for d in (_parse(v) for v in vals) if d is not None]
    _stamped_floor = min(stamps) if stamps else None
    return clock_floor()


def clock_floor() -> Optional[datetime]:
    """The task clock's go-live: settings.cm_task_clock_from when set (it
    wins, so an installation can move it), else the stamp migration 145
    wrote (load_clock_floor), else None."""
    from app.core.config import get_settings
    env = _parse(get_settings().cm_task_clock_from)
    return env if env is not None else _stamped_floor


def start_of(kind: str, own: Optional[datetime], entered: Optional[datetime],
             created: Optional[datetime], now: datetime) -> datetime:
    """When a computed row became owed: its own start (the question asked,
    the override proposed, the customer's yes), else when the change
    entered its status, else its creation; a sign-off owed at validation
    not before the change got there; never before the task clock's go-live
    (clock_floor). One rule for My Tasks and the sweep."""
    if kind == "sign_off" and own is not None and entered is not None:
        own = max(own, entered)
    start = own or entered or created or now
    floor = clock_floor()
    return max(start, floor) if floor is not None else start


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
                             "ppap_decision", "routing_deviation_decision"})
#: A customer wait is due at the next contact date (C4 default: +5 wd).
CUSTOMER_CONTACT_WD = 5
#: Rows that bring their own due date (the assessment's, the validation
#: issue engine's): the task rule leaves them alone.
OWN_DUE_PREFIXES = ("assessment", "validation_issue_",
                    # C33: an Assumed answer is confirmed by its own date
                    "confirm_assumption",
                    # §1: a deadline "not asked yet" too
                    "index_deadline_confirm")


#: Who sees a late row besides its owner (spec §0 one escalation rule):
#: department assessments, engine tasks and the computed rows that owe a
#: number or a decision (owed_items.WATCHED_KINDS) reach the lead's
#: "Overdue" group (notification_sweep, ChangeService.lead_escalations) and,
#: with RELEASE_V2, the overdue digest; Sales' stage rows reach the digest
#: (overdue_digest.SALES_ROWS). The rest (questions, plan feedback, the
#: onward hop, ...) is flagged Late in the owner's list only (cut 1). The UI
#: words the Late chip by this, so it never promises an escalation that does
#: not happen: no lead, no lead; RELEASE_V2 off, no digest.
LEAD_ESCALATED_KINDS = frozenset({"assessment", "costing_input", "sign_off",
                                  "internal_approval", "deviation_decision"})
DIGEST_KINDS = frozenset({"kickoff", "create_quote", "customer_response"})


def escalation_of(task: dict, change, leadless: bool = False) -> Optional[str]:
    """'lead_digest' | 'lead' | 'pm_digest' | 'pm' | 'digest' | None for a
    late My Tasks row. leadless: the change has no lead who can act
    (ChangeService.leadless_ids), so Project Management sees it (A6-03)."""
    digest = cm_switches.on("RELEASE_V2")
    if task["kind"] in LEAD_ESCALATED_KINDS:
        if leadless:
            return "pm_digest" if digest else "pm"
        if getattr(change, "lead_id", None) is not None:
            return "lead_digest" if digest else "lead"
        return "digest" if digest else None
    if (task["kind"] in DIGEST_KINDS and getattr(change, "customer_relevant", False)
            and digest):
        return "digest"
    return None


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
    idle: set = set()
    if on and tasks:
        await load_clock_floor(session)
        from app.services.change_service import ChangeService
        idle = await ChangeService.leadless_ids(
            session, [by_id[i] for i in {t["change_id"] for t in tasks} if i in by_id])
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
            start = start_of(t["kind"], start, since.get(c.id), c.created_at, now)
            # A4-03: an open price after a decline: 5 wd from the decline
            due = (add_wd(start, CUSTOMER_CONTACT_WD)
                   if t["kind"] in ("customer_response", "price_open")
                   else task_due(start, c, t["kind"]))
            if t["kind"] == "customer_response" and t.get("next_contact"):
                # §0: a customer wait is due at the next contact date (C4)
                nc = t["next_contact"]
                due = datetime(nc.year, nc.month, nc.day, 23, 59)
            # spec §0: a supplier wait pauses the late clock: due at expected-by
            if t.get("waiting_until") is not None:
                due = max(due, t["waiting_until"])
            t["due_date"] = due
            t["overdue"] = due < now
        t["late"] = is_late(due, now) if isinstance(due, datetime) else False
        t["escalation"] = escalation_of(t, c, c.id in idle)


def task_order(t: dict) -> tuple:
    """One order for the list: main before backup; "Needs you" on top, by
    due; then mine, overdue, soonest due (undated last), change number."""
    due = t.get("due_date")
    due_key = (due is None, due or datetime.max)
    if t.get("needs_you"):
        return (t.get("role") == "backup", 0, *due_key, t["change_number"])
    return (t.get("role") == "backup", 1, not t.get("mine", False),
            not t["overdue"], *due_key, t["change_number"])
