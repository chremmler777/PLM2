"""A hold's review date (Christoph 2026-11-02, migration 154).

Putting a change on hold takes the reason AND a "check again on" date
(default today + 2 weeks, at most ~3 months ahead). The run team's
"On hold: resume or cancel" task is due on that date and is not overdue
before it; on the date the lead (Project Management when the lead cannot
act) is reminded by a mailed notice; when nothing happens within 3 working
days after the date (resume, cancel or a new review date) it escalates to
the manager of Project Management (wf_departments.manager_id, migration
149) through the overdue digest and "Late in my departments". The lead or
PM can set a new date with a short reason; every date is on the changelog.

Kept small and model-free: the dates and the words, read by the
transition, My Tasks, the sweep and the digest alike."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

#: The dialog's default: two weeks from today.
DEFAULT_DAYS = 14
#: "max ~3 months" ahead.
MAX_DAYS = 92
#: Working days after the review date before it escalates.
ESCALATE_WD = 3


def today() -> date:
    """The business day (Toccoa), the day a person reads the date in."""
    from app.utils.clock import business_today
    return business_today()


def default_date(base: Optional[date] = None) -> date:
    return (base or today()) + timedelta(days=DEFAULT_DAYS)


def date_refusal(d: Optional[date], base: Optional[date] = None) -> Optional[str]:
    """Why this review date is not usable, or None."""
    base = base or today()
    if d is None:
        return "Say when the hold is checked again (the review date)"
    if d <= base:
        return ("The review date must be after today: the hold is checked "
                "again on a day still to come")
    if d > base + timedelta(days=MAX_DAYS):
        return (f"The review date can be at most {MAX_DAYS} days ahead "
                f"(by {(base + timedelta(days=MAX_DAYS)).isoformat()}): set a "
                "nearer date and move it again then")
    return None


def due_at(d: date) -> datetime:
    """The resume task is due at the end of the review day (naive UTC, as
    the other due dates): due that day, overdue only after it."""
    return datetime(d.year, d.month, d.day, 23, 59)


def escalates_at(d: date) -> datetime:
    from app.services.due_rules import add_wd
    return add_wd(due_at(d), ESCALATE_WD)


def reached(change, now: Optional[datetime] = None) -> bool:
    """The review day has come (the reminder is owed)."""
    d = getattr(change, "hold_review_date", None)
    if getattr(change, "status", None) != "on_hold" or d is None:
        return False
    from app.utils.clock import business_date_of
    return business_date_of(now or datetime.utcnow()) >= d


def escalated(change, now: Optional[datetime] = None) -> bool:
    """3 working days past the review date with nothing done."""
    d = getattr(change, "hold_review_date", None)
    if getattr(change, "status", None) != "on_hold" or d is None:
        return False
    return (now or datetime.utcnow()) >= escalates_at(d)


def header_line(change) -> Optional[str]:
    """'On hold until 16 Nov: waiting for the customer's drawing'."""
    if getattr(change, "status", None) != "on_hold":
        return None
    from app.core.display import fmt_date
    d = getattr(change, "hold_review_date", None)
    head = f"On hold until {fmt_date(d)}" if d else "On hold"
    why = (getattr(change, "hold_reason", None) or "").strip()
    return f"{head}: {why}" if why else head
