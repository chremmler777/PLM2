"""Central regression test for the NaiveUtcDatetime schema fix.

Production Postgres columns backing these fields are TIMESTAMP WITHOUT
TIME ZONE. asyncpg raises `DataError: can't subtract offset-naive and
offset-aware datetimes` if handed a tz-aware datetime for such a column.
The frontend sends tz-aware ISO-8601 strings (e.g. "...Z"), so the
schema layer must normalize these to naive UTC before they ever reach
the DB layer.

SQLite masks this bug: it silently truncates tzinfo on write/read
round-trips regardless of whether the validator ran, so an
integration-only test (POST then read back from the DB) cannot tell a
correctly-normalized value apart from a value that merely got mangled
by SQLite. These tests instead assert directly on the parsed Pydantic
model — the layer this fix actually targets — so they fail before the
fix and pass after it, independent of which DB backend runs the suite.
"""
from datetime import timezone

from app.schemas.change import ChangeUpdate, MeetingCreate, MeetingUpdate, AssessmentDueDateIn
from app.schemas.part import PartUpdate
from app.schemas.workflow import DueDateRequest


def test_meeting_create_normalizes_tz_aware_z_suffix():
    m = MeetingCreate(meeting_date="2026-07-07T12:00:00Z", participants=[{"name": "X"}])
    assert m.meeting_date.tzinfo is None
    assert m.meeting_date.hour == 12


def test_meeting_update_normalizes_tz_aware_offset():
    m = MeetingUpdate(meeting_date="2026-07-07T14:00:00+02:00")
    assert m.meeting_date.tzinfo is None
    assert m.meeting_date.hour == 12  # 14:00+02:00 -> 12:00 UTC


def test_change_update_required_by_date_normalizes_z_suffix():
    c = ChangeUpdate(required_by_date="2026-08-01T09:30:00Z")
    assert c.required_by_date.tzinfo is None
    assert c.required_by_date.hour == 9
    assert c.required_by_date.minute == 30


def test_change_update_required_by_date_accepts_naive():
    c = ChangeUpdate(required_by_date="2026-08-01T09:30:00")
    assert c.required_by_date.tzinfo is None
    assert c.required_by_date.hour == 9


def test_assessment_due_date_normalizes_tz_aware():
    a = AssessmentDueDateIn(due_date="2026-07-07T12:00:00Z")
    assert a.due_date.tzinfo is None


def test_workflow_due_date_request_normalizes_tz_aware():
    d = DueDateRequest(due_date="2026-07-07T12:00:00Z")
    assert d.due_date.tzinfo is None


def test_part_update_last_calibrated_at_normalizes_tz_aware():
    p = PartUpdate(last_calibrated_at="2026-07-07T12:00:00Z")
    assert p.last_calibrated_at.tzinfo is None


def test_naive_utc_conversion_is_actually_utc():
    """A non-UTC offset must be converted (not just stripped)."""
    m = MeetingCreate(meeting_date="2026-07-07T12:00:00+05:00", participants=[{"name": "X"}])
    expected = (
        __import__("datetime").datetime(2026, 7, 7, 12, 0, tzinfo=timezone(
            __import__("datetime").timedelta(hours=5)))
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    assert m.meeting_date == expected
    assert m.meeting_date.hour == 7
