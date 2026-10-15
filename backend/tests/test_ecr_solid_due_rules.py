"""ECR-solid C20 (spec §0 "Due dates, two rules", "One escalation rule"):

- Task: 2 working days; 1 when the change is urgent or others wait on it.
- Assessment: min(now + 7 d, deadline - 3 wd), deadline = quote deadline or
  need-by (the earlier), floor 2 wd (urgent 1 wd).
- Late (shows to the department, the lead's Overdue group, the digest) at
  due + 1 wd.
Switch ASSESSMENT_V2 off: the old flat 7 days."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import cm_switches, due_rules

MON = datetime(2026, 10, 12, 9, 0)        # a Monday
FRI = datetime(2026, 10, 16, 9, 0)
SAT = datetime(2026, 10, 17, 9, 0)


def _change(**kw):
    base = dict(priority="medium", required_by_date=None, release_due_date=None,
                customer_relevant=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_working_days_skip_the_weekend():
    assert due_rules.add_wd(MON, 2) == MON + timedelta(days=2)
    assert due_rules.add_wd(FRI, 1) == FRI + timedelta(days=3)       # Monday
    assert due_rules.add_wd(SAT, 1) == SAT + timedelta(days=2)       # Monday
    assert due_rules.sub_wd(MON, 1) == MON - timedelta(days=3)       # Friday
    assert due_rules.add_wd(MON, 0) == MON


def test_task_due_two_working_days_one_when_urgent_or_others_wait():
    c = _change()
    assert due_rules.task_due(FRI, c, "create_quote") == FRI + timedelta(days=4)
    assert due_rules.task_due(FRI, _change(priority="critical"), "create_quote") \
        == FRI + timedelta(days=3)
    # others wait on it: triage, new-index decision, ppap_decision, customer flip
    assert due_rules.task_due(MON, c, "ppap_decision") == MON + timedelta(days=1)


def test_assessment_due_takes_the_earlier_of_seven_days_and_the_deadline():
    # no deadline: now + 7 days
    assert due_rules.assessment_due(_change(), now=MON) == MON + timedelta(days=7)
    # quote deadline in 6 working days: due 3 wd before it
    dl = due_rules.add_wd(MON, 6)
    assert due_rules.assessment_due(_change(required_by_date=dl), now=MON) \
        == due_rules.sub_wd(dl, 3)
    # need-by earlier than the quote deadline wins
    need_by = due_rules.add_wd(MON, 7)
    got = due_rules.assessment_due(_change(required_by_date=MON + timedelta(days=30),
                                           release_due_date=need_by), now=MON)
    assert got == due_rules.sub_wd(need_by, 3)


def test_assessment_due_floor_two_working_days_urgent_one():
    tight = due_rules.add_wd(MON, 2)          # deadline - 3 wd lies in the past
    assert due_rules.assessment_due(_change(required_by_date=tight), now=MON) \
        == due_rules.add_wd(MON, 2)
    assert due_rules.assessment_due(
        _change(required_by_date=tight, priority="critical"), now=MON) \
        == due_rules.add_wd(MON, 1)


def test_late_is_one_working_day_after_due():
    due = FRI
    assert not due_rules.is_late(due, now=FRI + timedelta(days=2))   # Sunday
    assert due_rules.is_late(due, now=FRI + timedelta(days=3, minutes=1))
    assert not due_rules.is_late(None, now=FRI)


def test_switch_off_keeps_the_flat_seven_days(monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    dl = due_rules.add_wd(MON, 4)
    assert due_rules.assessment_due(_change(required_by_date=dl), now=MON) \
        == MON + timedelta(days=7)


def test_deadline_note_names_the_active_deadline():
    c = _change(required_by_date=datetime(2026, 10, 19))
    assert due_rules.deadline_of(c) == (datetime(2026, 10, 19), "quote")
    c = _change(release_due_date=datetime(2026, 10, 30),
                required_by_date=datetime(2026, 10, 19))
    assert due_rules.deadline_of(c) == (datetime(2026, 10, 19), "quote")
    assert due_rules.deadline_of(_change()) == (None, None)
    with pytest.raises(TypeError):
        due_rules.add_wd(MON, -1)
