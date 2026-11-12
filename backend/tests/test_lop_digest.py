"""Project LOP: badges for events, the daily digest, the weekly escalation summary,
and the switch that keeps LOP mail off."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.entities import User
from app.models.lop import LopLine
from app.models.notification import Notification
from app.services import ecr_mail
from app.services.ecr_mail import MAIL_KINDS
from app.services.lop_digest import digest_for, send_daily_digests, send_escalation_summary
from app.services.lop_service import _today

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"
WED = datetime(2026, 11, 11, 12, 30)            # 07:30 in New York
WED_DAY = date(2026, 11, 11)


def _d(days: int) -> str:
    return (_today() + timedelta(days=days)).isoformat()


async def _badges(session_factory, user_id, kind="lop_event"):
    async with session_factory() as s:
        return list((await s.execute(select(Notification).where(
            Notification.user_id == user_id, Notification.kind == kind)
            .order_by(Notification.id))).scalars().all())


async def _task(client, auth, project, title="Gauge concept", **kw):
    body = {"title": title, "department_id": project.apqp_id, "due_date": _d(10)}
    body.update(kw)
    r = await client.post(f"{BASE}/projects/{project.id}/lines", headers=auth, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _mk(session_factory, project, responsible, title="Line", **kw) -> int:
    """A line straight in the database (explicit dates, no badge)."""
    fields = dict(project_id=project.id, kind="task", title=title, responsible_id=responsible,
                  status="open", created_at=WED - timedelta(days=40),
                  last_update_at=WED - timedelta(days=1))
    fields.update(kw)
    async with session_factory() as s:
        ln = LopLine(**fields)
        s.add(ln)
        await s.commit()
        return ln.id


async def _digests(session_factory, user_id):
    return await _badges(session_factory, user_id, "lop_digest")


# ------------------------------------------------------------------ badges
async def test_ten_assignments_make_ten_badges_and_no_mail_kind(
        client, pm_auth, lop_project, session_factory):
    for i in range(10):
        await _task(client, pm_auth, lop_project, f"Task {i}")
    got = await _badges(session_factory, lop_project.quality_user_id)
    assert len(got) == 10
    assert {n.kind for n in got} == {"lop_event"} and "lop_event" not in MAIL_KINDS
    first = got[0]
    assert first.title == "LOP lop1: new line for you" and first.body == "Task 0"
    assert first.link == f"/projects/{lop_project.id}/lop"
    assert not ecr_mail.mailable(first)


async def test_no_badge_when_the_actor_is_the_recipient(client, pm_auth, lop_project, session_factory):
    await _task(client, pm_auth, lop_project, "Mine", responsible_id=lop_project.pm_id)
    assert await _badges(session_factory, lop_project.pm_id) == []


async def test_reassigning_gives_the_new_person_a_badge(client, pm_auth, lop_project, session_factory):
    lid = await _task(client, pm_auth, lop_project, "Move me")
    r = await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth,
                           json={"responsible_id": lop_project.sales_user_id})
    assert r.status_code == 200, r.text
    got = await _badges(session_factory, lop_project.sales_user_id)
    assert [n.body for n in got] == ["Move me"]
    # an unchanged responsible makes no second badge
    await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth,
                       json={"responsible_id": lop_project.sales_user_id})
    assert len(await _badges(session_factory, lop_project.sales_user_id)) == 1


async def test_done_check_goes_to_the_pm_and_reopening_back_to_the_responsible(
        client, pm_auth, quality_auth, lop_project, session_factory):
    lid = await _task(client, pm_auth, lop_project, "Check me")
    r = await client.patch(f"{BASE}/lines/{lid}", headers=quality_auth, json={"status": "done_check"})
    assert r.status_code == 200, r.text
    pm = await _badges(session_factory, lop_project.pm_id)
    assert len(pm) == 1 and pm[0].body == "Check me" and "done" in pm[0].title.lower()
    before = len(await _badges(session_factory, lop_project.quality_user_id))
    r = await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth, json={"status": "in_work"})
    assert r.status_code == 200, r.text
    got = await _badges(session_factory, lop_project.quality_user_id)
    assert len(got) == before + 1 and "again" in got[-1].title.lower()
    # closing then reopening a closed line also tells the responsible
    await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth, json={"status": "closed"})
    await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth, json={"status": "open"})
    assert len(await _badges(session_factory, lop_project.quality_user_id)) == before + 2


async def test_pinning_a_topic_tells_the_person(lop_project, session_factory, admin_auth):
    from app.services.lop_service import LopService
    async with session_factory() as s:
        pm = await s.get(User, lop_project.pm_id)
        await LopService.pin_pdb_topic(
            s, pm, lop_project.id, {"id": 9, "issue": "Burr on cover", "department": None},
            responsible_id=lop_project.quality_user_id, due_date=_today() + timedelta(days=5))
    got = await _badges(session_factory, lop_project.quality_user_id)
    assert len(got) == 1 and got[0].body == "Burr on cover"


async def test_adding_a_whole_gate_is_one_badge_per_person(
        client, pm_auth, lop_project, session_factory, seed_forms):
    r = await client.post(f"/api/v1/sep/projects/{lop_project.id}/activate", headers=pm_auth)
    assert r.status_code == 201, r.text
    from app.models.sep import SepGate
    async with session_factory() as s:
        gate = (await s.execute(select(SepGate).where(
            SepGate.project_id == lop_project.id, SepGate.code == "K0/RG1"))).scalar_one().id
    r = await client.post(f"{BASE}/projects/{lop_project.id}/lines/from-sep", headers=pm_auth,
                          json={"gate_id": gate, "only_open": True})
    assert r.status_code == 201 and r.json()["added"] > 3
    got = await _badges(session_factory, lop_project.quality_user_id)
    assert len(got) == 1 and "new lines for you" in got[0].title
    assert await _badges(session_factory, lop_project.pm_id) == []      # the actor


# ---------------------------------------------------------------- the switch
async def test_lop_mail_is_off_until_switched_on(monkeypatch, session_factory):
    async with session_factory() as s:
        s.add_all([Notification(user_id=1, kind=k, title="t") for k in
                   ("lop_digest", "lop_escalation", "lop_minutes", "task_assigned")])
        await s.commit()
        rows = {n.kind: n for n in (await s.execute(select(Notification))).scalars().all()}
    assert get_settings().lop_mail_enabled is False
    for k in ("lop_digest", "lop_escalation", "lop_minutes"):
        assert not ecr_mail.mailable(rows[k])
    assert ecr_mail.mailable(rows["task_assigned"])
    monkeypatch.setattr(get_settings(), "lop_mail_enabled", True)
    for k in ("lop_digest", "lop_escalation", "lop_minutes", "task_assigned"):
        assert ecr_mail.mailable(rows[k])


async def test_switched_off_lop_notifications_are_stamped_not_mailed_later(
        monkeypatch, session_factory, seed):
    monkeypatch.setattr(get_settings(), "ecr_mail_enabled", True)
    monkeypatch.setattr(ecr_mail, "enabled", lambda: True)
    sent = []
    async with session_factory() as s:
        u = await s.get(User, seed["engineer_id"])
        u.email = "eng@test.io"
        s.add_all([Notification(user_id=u.id, kind="lop_digest", title="d"),
                   Notification(user_id=u.id, kind="task_assigned", title="a")])
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=sent.append) == 1
        assert [m.subject for m in sent] and all("d" != m.subject for m in sent)
        rows = (await s.execute(select(Notification))).scalars().all()
        assert all(n.mailed_at is not None for n in rows)
    monkeypatch.setattr(get_settings(), "lop_mail_enabled", True)
    async with session_factory() as s:
        assert await ecr_mail.send_pending(s, sender=sent.append) == 0     # no backlog


async def test_lop_kinds_are_mailed():
    assert {"lop_digest", "lop_escalation", "lop_minutes"} <= MAIL_KINDS


# ------------------------------------------------------------------- digest
async def test_one_digest_per_person_per_day(lop_project, session_factory):
    q, sl = lop_project.quality_user_id, lop_project.sales_user_id
    await _mk(session_factory, lop_project, q, due_date=WED_DAY + timedelta(days=2))
    await _mk(session_factory, lop_project, sl, due_date=WED_DAY + timedelta(days=2))
    async with session_factory() as s:
        assert await send_daily_digests(s, WED) == 2
    async with session_factory() as s:
        assert await send_daily_digests(s, WED + timedelta(hours=2)) == 0
    for uid in (q, sl):
        got = await _digests(session_factory, uid)
        assert len(got) == 1 and got[0].subject_key == "lop_digest:2026-11-11"
        assert got[0].link == "/my-tasks" and got[0].title == "LOP: 1 lines need you"


async def test_no_digest_before_seven_or_at_the_weekend(lop_project, session_factory):
    await _mk(session_factory, lop_project, lop_project.quality_user_id,
              due_date=WED_DAY + timedelta(days=2))
    async with session_factory() as s:
        assert await send_daily_digests(s, datetime(2026, 11, 11, 11, 30)) == 0   # 06:30 local
        assert await send_daily_digests(s, datetime(2026, 11, 14, 12, 30)) == 0   # Saturday
        assert await send_daily_digests(s, datetime(2026, 11, 15, 12, 30)) == 0   # Sunday
        assert await send_daily_digests(s, datetime(2026, 11, 11, 12, 0)) == 1    # 07:00 sharp


async def test_digest_only_inside_the_morning_window(lop_project, session_factory):
    """No mail when something changes: a line given at 10:00 waits for the next morning."""
    await _mk(session_factory, lop_project, lop_project.quality_user_id,
              due_date=WED_DAY + timedelta(days=2))
    async with session_factory() as s:
        assert await send_daily_digests(s, datetime(2026, 11, 11, 19, 0)) == 0    # Wed 14:00 local
        assert await send_daily_digests(s, datetime(2026, 11, 11, 12, 10)) == 1   # Wed 07:10
        assert await send_daily_digests(s, datetime(2026, 11, 12, 14, 0)) == 0    # Thu 09:00
        assert await send_daily_digests(s, datetime(2026, 11, 12, 13, 50)) == 1   # Thu 08:50
    await _mk(session_factory, lop_project, lop_project.sales_user_id, "Given at 10:00",
              due_date=WED_DAY + timedelta(days=4), created_at=datetime(2026, 11, 13, 15, 0))
    async with session_factory() as s:
        assert await send_daily_digests(s, datetime(2026, 11, 13, 15, 15)) == 0   # Fri 10:15



async def test_digest_lists_new_due_soon_overdue_stale(lop_project, session_factory):
    q = lop_project.quality_user_id
    new = await _mk(session_factory, lop_project, q, "Brand new", created_at=WED - timedelta(hours=3),
                    due_date=WED_DAY + timedelta(days=30))
    soon = await _mk(session_factory, lop_project, q, "Soon", due_date=WED_DAY + timedelta(days=3))
    late = await _mk(session_factory, lop_project, q, "Late", due_date=WED_DAY - timedelta(days=4))
    stale = await _mk(session_factory, lop_project, q, "Stale", due_date=WED_DAY + timedelta(days=30),
                      last_update_at=WED - timedelta(days=20))
    far = await _mk(session_factory, lop_project, q, "Far", due_date=WED_DAY + timedelta(days=30))
    async with session_factory() as s:
        title, body = await digest_for(s, await s.get(User, q), WED_DAY, now=WED)
    assert title == "LOP: 4 lines need you"
    sections = {}
    cur = None
    for row in body.splitlines():
        if row and not row.startswith((" ", "#")) and row != "lop1":
            cur = row
            sections[cur] = []
        elif row.strip().startswith("#"):
            sections[cur].append(row.strip())
    assert list(sections) == ["New for you", "Due within 3 days", "Overdue", "No update for 14 days"]
    assert sections["New for you"] == [f"#{new} Brand new | due {WED_DAY + timedelta(days=30)}"]
    assert sections["Due within 3 days"] == [f"#{soon} Soon | due {WED_DAY + timedelta(days=3)}"]
    assert sections["Overdue"][0].startswith(f"#{late} Late | due {WED_DAY - timedelta(days=4)}")
    assert "4 days late" in sections["Overdue"][0]
    assert sections["No update for 14 days"][0].startswith(f"#{stale} Stale")
    assert f"#{far}" not in body
    assert "lop1" in body                                  # grouped by project code


async def test_new_may_repeat_a_line_that_is_also_due_soon(lop_project, session_factory):
    q = lop_project.quality_user_id
    lid = await _mk(session_factory, lop_project, q, "Both", created_at=WED - timedelta(hours=2),
                    due_date=WED_DAY + timedelta(days=1))
    async with session_factory() as s:
        title, body = await digest_for(s, await s.get(User, q), WED_DAY, now=WED)
    assert title == "LOP: 1 lines need you" and body.count(f"#{lid} ") == 2


async def test_new_since_the_previous_digest(lop_project, session_factory):
    q = lop_project.quality_user_id
    old = await _mk(session_factory, lop_project, q, "Seen", created_at=WED - timedelta(hours=30),
                    due_date=WED_DAY + timedelta(days=30))
    async with session_factory() as s:
        s.add(Notification(user_id=q, kind="lop_digest", title="x", subject_key="lop_digest:old",
                           created_at=WED - timedelta(hours=40)))
        await s.commit()
        title, body = await digest_for(s, await s.get(User, q), WED_DAY, now=WED)
    assert "New for you" in body and f"#{old} " in body       # newer than the previous digest


async def test_digest_shows_state_at_send_time(client, pm_auth, lop_project, session_factory):
    q, sl = lop_project.quality_user_id, lop_project.sales_user_id
    lid = await _mk(session_factory, lop_project, q, "Moves", created_at=WED - timedelta(hours=2),
                    due_date=WED_DAY + timedelta(days=30))
    async with session_factory() as s:
        (await s.get(LopLine, lid)).responsible_id = sl
        await s.commit()
    async with session_factory() as s:
        assert await digest_for(s, await s.get(User, q), WED_DAY, now=WED) is None
        assert (await digest_for(s, await s.get(User, sl), WED_DAY, now=WED)) is not None


async def test_nothing_to_report_means_no_digest(lop_project, session_factory):
    await _mk(session_factory, lop_project, lop_project.quality_user_id, "Calm",
              due_date=WED_DAY + timedelta(days=30))
    await _mk(session_factory, lop_project, lop_project.quality_user_id, "Done",
              status="closed", due_date=WED_DAY - timedelta(days=30))
    async with session_factory() as s:
        assert await digest_for(s, await s.get(User, lop_project.quality_user_id),
                                WED_DAY, now=WED) is None
        assert await send_daily_digests(s, WED) == 0


async def test_pm_digest_lists_waiting_for_check(lop_project, session_factory):
    q = lop_project.quality_user_id
    lid = await _mk(session_factory, lop_project, q, "Reported done", status="done_check",
                    due_date=WED_DAY - timedelta(days=2))
    async with session_factory() as s:
        pm = await digest_for(s, await s.get(User, lop_project.pm_id), WED_DAY, now=WED)
        assert pm is not None and pm[0] == "LOP: 1 lines need you"
        assert "Waiting for your check" in pm[1] and f"#{lid} Reported done" in pm[1]
        assert "Overdue" not in pm[1]
        # the one who reported it is not nagged about a line that waits for the PM
        assert await digest_for(s, await s.get(User, q), WED_DAY, now=WED) is None
        assert await send_daily_digests(s, WED) == 1


async def test_deactivated_responsible_gets_no_digest_and_line_counts_as_no_name(
        lop_project, session_factory):
    q = lop_project.quality_user_id
    await _mk(session_factory, lop_project, q, "Orphan", due_date=WED_DAY - timedelta(days=5))
    async with session_factory() as s:
        (await s.get(User, q)).is_active = False
        await s.commit()
    async with session_factory() as s:
        assert await send_daily_digests(s, WED) == 0
    assert await _digests(session_factory, q) == []


async def test_a_responsible_who_left_the_team_gets_no_digest(client, admin_auth, lop_project, session_factory):
    q = lop_project.quality_user_id
    await _mk(session_factory, lop_project, q, "Gone", due_date=WED_DAY - timedelta(days=5))
    r = await client.put(f"/api/v1/projects/{lop_project.id}/team", headers=admin_auth,
                         json={"department_id": lop_project.apqp_id, "user_id": None})
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert await send_daily_digests(s, WED) == 0


async def test_unpinned_pdb_topics_are_in_nobodys_digest(lop_project, session_factory, monkeypatch):
    from app.services import pdb_client

    async def boom(*a, **k):
        raise AssertionError("the digest must not call PDB")
    for name in ("project_status", "project_topics", "open_topics"):
        if hasattr(pdb_client, name):
            monkeypatch.setattr(pdb_client, name, boom)
    await _mk(session_factory, lop_project, None, "Unpinned", kind="pdb_topic", ref_key="5")
    async with session_factory() as s:
        assert await send_daily_digests(s, WED) == 0
        for uid in (lop_project.pm_id, lop_project.quality_user_id):
            assert await digest_for(s, await s.get(User, uid), WED_DAY, now=WED) is None


# --------------------------------------------------------------- escalation
MON = datetime(2026, 11, 16, 12, 30)


async def _stale_project(session_factory, project):
    await _mk(session_factory, project, project.quality_user_id, "Nobody met",
              due_date=date(2026, 12, 1), created_at=MON - timedelta(days=20))


async def test_escalation_summary_on_monday_to_configured_people_only(
        monkeypatch, lop_project, session_factory):
    monkeypatch.setattr(get_settings(), "lop_escalation_recipients", "quality, sales@test.io, nobody")
    await _stale_project(session_factory, lop_project)
    async with session_factory() as s:
        assert await send_escalation_summary(s, WED) == 0                      # not a Monday
        assert await send_escalation_summary(s, datetime(2026, 11, 16, 11, 0)) == 0   # too early
        assert await send_escalation_summary(s, datetime(2026, 11, 16, 19, 0)) == 0   # 14:00, too late
        assert await send_escalation_summary(s, datetime(2026, 11, 16, 14, 0)) == 0   # 09:00, too late
        assert await send_escalation_summary(s, MON) == 2
        assert await send_escalation_summary(s, MON + timedelta(hours=1)) == 0
    got = await _badges(session_factory, lop_project.quality_user_id, "lop_escalation")
    assert len(got) == 1 and got[0].subject_key == "lop_escalation:2026-W47"
    assert "lop1" in got[0].body and "no LOP meeting" in got[0].body
    assert await _badges(session_factory, lop_project.pm_id, "lop_escalation") == []
    assert not ecr_mail.mailable(got[0])


async def test_escalation_lists_lines_too(monkeypatch, lop_project, session_factory):
    from app.models.lop import LopMeeting, LopMeetingMark
    monkeypatch.setattr(get_settings(), "lop_escalation_recipients", "quality")
    lid = await _mk(session_factory, lop_project, lop_project.sales_user_id, "Hand escalated",
                    due_date=date(2026, 12, 1), created_at=MON - timedelta(days=3))
    async with session_factory() as s:
        m = LopMeeting(project_id=lop_project.id, held_on=MON.date() - timedelta(days=2),
                       closed_at=MON - timedelta(days=2))
        s.add(m)
        await s.flush()
        s.add(LopMeetingMark(meeting_id=m.id, line_id=lid, mark="escalated"))
        await s.commit()
        assert await send_escalation_summary(s, MON) == 1
    got = await _badges(session_factory, lop_project.quality_user_id, "lop_escalation")
    assert f"#{lid} Hand escalated" in got[0].body


async def test_escalation_with_nothing_or_nobody_sends_nothing(monkeypatch, lop_project, session_factory):
    async with session_factory() as s:
        monkeypatch.setattr(get_settings(), "lop_escalation_recipients", "quality")
        assert await send_escalation_summary(s, MON) == 0                      # empty list
        await _stale_project(session_factory, lop_project)
        monkeypatch.setattr(get_settings(), "lop_escalation_recipients", "")
        assert await send_escalation_summary(s, MON) == 0                      # nobody configured
