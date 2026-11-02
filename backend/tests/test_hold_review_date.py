"""On hold with a review date (Christoph 2026-11-02, migration 154).

- a hold takes the reason AND a "check again on" date (default today + 2
  weeks, at most ~3 months, never today or earlier); the date is on the
  history and on the change ("On hold until <date>: <reason>");
- the resume task is due on that date and is not overdue before it; 3
  working days after it the row is late and Project Management's manager
  sees it (escalation "pm_manager", the overdue digest);
- on the review date the lead is reminded by a mailable notice (once per
  date);
- the lead or PM sets a new date with a short reason (history); others are
  refused."""
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.models.change import ChangeChangelog, ChangeRequest
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from app.services import hold_review
from tests.conftest import KEEP_LEAD_RULE, login

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def depts(session_factory, seed):
    ids = {}
    async with session_factory() as s:
        for i, (n, cust, internal) in enumerate((
                ("Sales", True, False), ("Project Manager", True, False),
                ("Development", False, True), ("Quality", False, False))):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=cust, can_start_internal_change=internal)
            s.add(d); await s.flush(); ids[n] = d.id
        await s.commit()
    return ids


async def _user(session_factory, seed, name, dept_id):
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=name.lower(),
                 email=f"{name.lower()}@test.io", full_name=name,
                 hashed_password="x", role="engineer", is_active=True)
        s.add(u); await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept_id))
        await s.commit()
        return u.id, u.email


async def _held(client, seed, depts, session_factory, **extra):
    """An internal change led by a Development member, put on hold."""
    dev_id, mail = await _user(session_factory, seed, "Devon", depts["Development"])
    dev = await login(client, mail, admin=False)
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "fix", "reason": "r",
        "change_type": "physical_part", "customer_relevant": False},
        headers={**dev, KEEP_LEAD_RULE: "1"})
    assert res.status_code in (200, 201), res.text
    c = res.json()
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", headers=dev,
                            json={"to_status": "on_hold",
                                  "reason": "waiting for the tool trial", **extra})
    return dev_id, dev, c, res


async def _set_review(session_factory, cid, d):
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(hold_review_date=d))
        await s.commit()


async def _resume_rows(client, headers, cid):
    return [t for t in (await client.get("/api/v1/changes/my-tasks",
                                         headers=headers)).json()
            if t["change_id"] == cid and t["kind"] == "hold_resume"]


async def test_hold_default_date_on_change_and_history(client, seed, depts, session_factory):
    _, dev, c, res = await _held(client, seed, depts, session_factory)
    assert res.status_code == 200, res.text
    body = res.json()
    want = hold_review.default_date()
    assert body["hold_review_date"] == want.isoformat()
    assert body["hold_reason"] == "waiting for the tool trial"
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == c["id"],
            ChangeChangelog.field_name == "hold_review_date"))).scalars().all()
    assert len(rows) == 1 and rows[0].action == "hold_review_set"
    assert want.isoformat() in rows[0].new_value
    line = hold_review.header_line(type("C", (), {
        "status": "on_hold", "hold_review_date": want,
        "hold_reason": "waiting for the tool trial"})())
    assert line.startswith("On hold until ") and line.endswith(": waiting for the tool trial")


async def test_hold_date_in_range_only(client, seed, depts, session_factory):
    today = hold_review.today()
    _, _, _, res = await _held(client, seed, depts, session_factory,
                               hold_until=(today + timedelta(days=120)).isoformat())
    assert res.status_code == 400 and "at most" in res.json()["detail"]
    # today is no review date either (a second change by the same lead)
    dev = await login(client, "devon@test.io", admin=False)
    c = (await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "fix 2", "reason": "r",
        "change_type": "physical_part", "customer_relevant": False},
        headers={**dev, KEEP_LEAD_RULE: "1"})).json()
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", headers=dev,
                            json={"to_status": "on_hold", "reason": "waiting",
                                  "hold_until": today.isoformat()})
    assert res.status_code == 400 and "after today" in res.json()["detail"]
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", headers=dev,
                            json={"to_status": "on_hold", "reason": "waiting",
                                  "hold_until": (today + timedelta(days=30)).isoformat()})
    assert res.status_code == 200
    assert res.json()["hold_review_date"] == (today + timedelta(days=30)).isoformat()


async def test_resume_task_due_on_review_date_not_before(client, seed, depts, session_factory):
    _, dev, c, res = await _held(client, seed, depts, session_factory)
    assert res.status_code == 200
    [row] = await _resume_rows(client, dev, c["id"])
    assert row["hold_review_date"] == hold_review.default_date().isoformat()
    assert row["due_date"].startswith(hold_review.default_date().isoformat())
    assert row["overdue"] is False and row["late"] is False
    assert row["escalation"] is None
    # long past the review date: overdue, late, Project Management's manager
    await _set_review(session_factory, c["id"], date.today() - timedelta(days=10))
    [row] = await _resume_rows(client, dev, c["id"])
    assert row["overdue"] is True and row["late"] is True
    assert row["escalation"] == "pm_manager"
    # the day after the review date: overdue for the lead, not escalated yet
    await _set_review(session_factory, c["id"], date.today() - timedelta(days=1))
    [row] = await _resume_rows(client, dev, c["id"])
    assert row["overdue"] is True and row["late"] is False


async def test_new_review_date_by_lead_with_reason(client, seed, depts, session_factory):
    _, dev, c, _ = await _held(client, seed, depts, session_factory)
    url = f"/api/v1/changes/{c['id']}/hold-review"
    new = hold_review.today() + timedelta(days=40)
    res = await client.put(url, headers=dev, json={"review_date": new.isoformat(),
                                                   "reason": "x"})
    assert res.status_code == 400 and "few words" in res.json()["detail"]
    res = await client.put(url, headers=dev, json={
        "review_date": new.isoformat(), "reason": "customer moved the SOP"})
    assert res.status_code == 200, res.text
    assert res.json()["hold_review_date"] == new.isoformat()
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == c["id"],
            ChangeChangelog.action == "hold_review_moved"))).scalars().all()
    assert len(rows) == 1 and rows[0].notes == "customer moved the SOP"
    # Sales may not move it
    _, mail = await _user(session_factory, seed, "Sally", depts["Sales"])
    sally = await login(client, mail, admin=False)
    res = await client.put(url, headers=sally, json={
        "review_date": (new + timedelta(days=1)).isoformat(), "reason": "later please"})
    assert res.status_code == 403
    # Project Management may
    _, mail = await _user(session_factory, seed, "Pam", depts["Project Manager"])
    pam = await login(client, mail, admin=False)
    res = await client.put(url, headers=pam, json={
        "review_date": (new + timedelta(days=1)).isoformat(), "reason": "later please"})
    assert res.status_code == 200, res.text
    # a resumed change has no review date to move
    await client.post(f"/api/v1/changes/{c['id']}/transition", headers=dev,
                      json={"to_status": "captured"})
    res = await client.put(url, headers=dev, json={
        "review_date": (new + timedelta(days=2)).isoformat(), "reason": "later please"})
    assert res.status_code == 400


async def test_review_day_reminds_the_lead_once_mailable(client, seed, depts, session_factory):
    from app.services.ecr_mail import mailable
    from app.services.notification_sweep import run_notification_sweep
    dev_id, _, c, _ = await _held(client, seed, depts, session_factory)
    async with session_factory() as s:
        counts = await run_notification_sweep(s)
        await s.commit()
    assert counts["hold_review"] == 0          # not the day yet
    await _set_review(session_factory, c["id"], hold_review.today())
    for _ in range(2):
        async with session_factory() as s:
            await run_notification_sweep(s)
            await s.commit()
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.kind == "hold_review"))).scalars().all()
    assert [n.user_id for n in notes] == [dev_id]
    assert mailable(notes[0]) and "review date" in notes[0].body


async def test_escalates_to_pm_manager_in_digest(client, seed, depts, session_factory):
    from app.services.overdue_digest import late_entries, send_overdue_digest
    _, _, c, _ = await _held(client, seed, depts, session_factory)
    boss_id, _ = await _user(session_factory, seed, "Steven", depts["Project Manager"])
    async with session_factory() as s:
        await s.execute(update(Department).where(Department.id == depts["Project Manager"])
                        .values(manager_id=boss_id))
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, c["id"])
        assert [e for e in await late_entries(s, {change.id: change}, datetime.utcnow())
                if e["kind"] == "hold_review"] == []
    await _set_review(session_factory, c["id"], date.today() - timedelta(days=10))
    async with session_factory() as s:
        change = await s.get(ChangeRequest, c["id"])
        [e] = [e for e in await late_entries(s, {change.id: change}, datetime.utcnow())
               if e["kind"] == "hold_review"]
        assert e["department_id"] == depts["Project Manager"]
        await send_overdue_digest(s)
        await s.commit()
    async with session_factory() as s:
        digest = (await s.execute(select(Notification).where(
            Notification.kind == "overdue_digest",
            Notification.user_id == boss_id))).scalars().all()
    assert len(digest) == 1 and "review date" in digest[0].body
