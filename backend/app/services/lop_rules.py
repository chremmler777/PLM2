"""Control rules for a project's list of open points (LOP).

Pure functions on a ``LineState``: no database, and "today" is always passed
in. An unpinned PDB topic is only a reference: it is never late and never
stale, and only a pinned one follows the task rules.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass
class LineState:
    kind: str
    status: str
    responsible_id: int | None
    responsible_active: bool
    due_date: date | None
    first_due_date: date | None
    next_check_date: date | None
    last_update_at: datetime | None
    closed_at: datetime | None
    pinned: bool
    reopened: bool = False


def is_open(s: LineState) -> bool:
    return s.status != "closed"


def _unpinned_pdb(s: LineState) -> bool:
    return s.kind == "pdb_topic" and not s.pinned


def _tracked(s: LineState) -> bool:
    """Open and subject to the late / stale rules."""
    return is_open(s) and not _unpinned_pdb(s)


def days_late(s: LineState, today: date) -> int:
    """Whole days past the due date; 0 when not late (due date only)."""
    if not _tracked(s) or s.due_date is None or s.due_date >= today:
        return 0
    return (today - s.due_date).days


def missed_check(s: LineState, today: date) -> bool:
    return (_tracked(s) and s.next_check_date is not None
            and s.next_check_date < today)


def is_late(s: LineState, today: date) -> bool:
    return days_late(s, today) > 0 or missed_check(s, today)


def is_stale(s: LineState, today: date, stale_days: int) -> bool:
    if not _tracked(s):
        return False
    if s.last_update_at is None:
        return True
    return (today - s.last_update_at.date()).days >= stale_days


def under_control(s: LineState) -> bool:
    """An active responsible person and a due or next-check date."""
    return (s.responsible_id is not None and s.responsible_active
            and (s.due_date is not None or s.next_check_date is not None))


def due_soon(s: LineState, today: date, window_days: int) -> bool:
    if not _tracked(s) or s.due_date is None:
        return False
    return 0 <= (s.due_date - today).days <= window_days


def closed_on_time(s: LineState) -> bool | None:
    """Closed on or before the first due date; None when never dated.

    A line that was ever reopened is never on time.
    """
    if s.reopened:
        return False
    if s.first_due_date is None or s.closed_at is None:
        return None
    return s.closed_at.date() <= s.first_due_date


def group_of(s: LineState, today: date, stale_days: int,
             last_meeting: date | None, created_on: date) -> str:
    if not is_open(s):
        return "closed"
    if _unpinned_pdb(s):
        return "pdb"
    if is_late(s, today):
        return "overdue"
    end_of_week = today + timedelta(days=7 - today.isoweekday())
    if s.due_date is not None and today <= s.due_date <= end_of_week:
        return "due_this_week"
    if s.status == "done_check":
        return "waiting_check"
    is_new = (s.status == "new") if last_meeting is None else created_on > last_meeting
    if is_new:
        return "new"
    if is_stale(s, today, stale_days):
        return "stale"
    return "other"


def needs_escalation(marks: list[tuple[bool, bool]]) -> bool:
    """Marks are newest first as (was_late, was_stale); true when the two
    newest meetings each had the line late or stale."""
    return len(marks) >= 2 and all(late or stale for late, stale in marks[:2])
