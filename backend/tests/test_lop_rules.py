"""Pure control rules for the project LOP (no database)."""
from datetime import date, datetime

from app.services.lop_rules import (
    LineState, closed_on_time, days_late, due_soon, group_of, is_late,
    is_open, is_stale, missed_check, needs_escalation, under_control,
)

T = date(2026, 11, 11)  # a Wednesday


def line(**kw):
    base = dict(
        kind="task", status="open", responsible_id=5, responsible_active=True,
        due_date=None, first_due_date=None, next_check_date=None,
        last_update_at=datetime(2026, 11, 10), closed_at=None, pinned=False,
    )
    return LineState(**{**base, **kw})


def test_overdue_counts_days():
    assert days_late(line(due_date=date(2026, 11, 3)), T) == 8


def test_due_today_is_not_late():
    assert days_late(line(due_date=T), T) == 0


def test_closed_line_is_never_late():
    s = line(due_date=date(2026, 11, 3), status="closed")
    assert not is_late(s, T) and not is_open(s)


def test_missed_check_is_late():
    s = line(next_check_date=date(2026, 11, 10))
    assert missed_check(s, T) and is_late(s, T)
    assert not missed_check(line(next_check_date=T), T)


def test_stale_at_14_days_not_13():
    assert is_stale(line(last_update_at=datetime(2026, 10, 28)), T, 14)
    assert not is_stale(line(last_update_at=datetime(2026, 10, 29)), T, 14)


def test_never_updated_open_line_is_stale_but_closed_is_not():
    assert is_stale(line(last_update_at=None), T, 14)
    assert not is_stale(line(last_update_at=None, status="closed"), T, 14)


def test_no_name_or_no_date_is_not_under_control():
    assert not under_control(line(responsible_id=None, due_date=T))
    assert not under_control(line())
    assert under_control(line(next_check_date=T))


def test_inactive_responsible_is_not_under_control():
    assert not under_control(line(responsible_active=False, due_date=T))


def test_unpinned_pdb_topic_is_never_late_but_not_under_control():
    s = line(kind="pdb_topic", responsible_id=None, last_update_at=None,
             due_date=date(2026, 11, 3))
    assert not is_late(s, T) and not is_stale(s, T, 14)
    assert not under_control(s) and group_of(s, T, 14, None, T) == "pdb"


def test_pinned_pdb_topic_follows_task_rules():
    s = line(kind="pdb_topic", pinned=True, due_date=date(2026, 11, 3))
    assert is_late(s, T) and group_of(s, T, 14, None, T) == "overdue"


def test_due_soon_window():
    assert due_soon(line(due_date=date(2026, 11, 14)), T, 3)
    assert not due_soon(line(due_date=date(2026, 11, 15)), T, 3)
    assert not due_soon(line(due_date=date(2026, 11, 10)), T, 3)
    assert not due_soon(line(), T, 3)


def test_on_time_uses_first_due_date():
    assert closed_on_time(line(
        status="closed", closed_at=datetime(2026, 11, 5),
        first_due_date=date(2026, 11, 3), due_date=date(2026, 11, 6))) is False
    assert closed_on_time(line(
        status="closed", closed_at=datetime(2026, 11, 3, 15),
        first_due_date=date(2026, 11, 3), due_date=date(2026, 11, 1))) is True


def test_on_time_none_when_never_dated():
    assert closed_on_time(line(status="closed", closed_at=datetime(2026, 11, 5))) is None


def test_reopened_line_is_never_on_time():
    s = line(status="closed", closed_at=datetime(2026, 11, 2),
             first_due_date=date(2026, 11, 3), reopened=True)
    assert closed_on_time(s) is False


def test_group_order_overdue_beats_waiting_check():
    s = line(status="done_check", due_date=date(2026, 11, 3))
    assert group_of(s, T, 14, None, T) == "overdue"


def test_group_closed_and_due_this_week():
    assert group_of(line(status="closed"), T, 14, None, T) == "closed"
    assert group_of(line(due_date=date(2026, 11, 15)), T, 14, None, T) == "due_this_week"
    assert group_of(line(due_date=date(2026, 11, 16)), T, 14, None, T) == "other"


def test_group_waiting_new_stale_other():
    assert group_of(line(status="done_check"), T, 14, None, T) == "waiting_check"
    assert group_of(line(status="new"), T, 14, None, date(2026, 11, 1)) == "new"
    assert group_of(line(), T, 14, date(2026, 11, 5), date(2026, 11, 6)) == "new"
    assert group_of(line(), T, 14, date(2026, 11, 5), date(2026, 11, 5)) == "other"
    assert group_of(line(status="new"), T, 14, date(2026, 11, 5), date(2026, 11, 1)) == "other"
    assert group_of(line(last_update_at=datetime(2026, 10, 1)), T, 14, None, T) == "stale"


def test_escalation_needs_two_meetings_in_a_row():
    assert needs_escalation([(True, False), (False, True)])
    assert not needs_escalation([(True, False), (False, False)])
    assert not needs_escalation([(True, False)])
    assert not needs_escalation([])
