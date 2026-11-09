"""ECR-solid lane L3, review loop 1 (spec §0 one escalation rule,
notifications, My Tasks):

- the reminder loop's sweep is committed (sweep_once), not rolled back;
- a sweep notice is sent once per item, read or not, and only the
  immediate class is mailed (late notices, reminders, backup copies are
  badges);
- one lateness test everywhere: a Friday due date is not late on the
  weekend and does not flip on Monday morning;
- an owned unlinked assessment is reminded on its due date;
- a read-only approver or lead gets no row it could not act on, and the
  Project Management fallback takes the approval;
- rows owed mid-status count their due from when they became owed;
- sign-off rows follow COMMERCIAL_V2 / RELEASE_V2;
- the digest shows a non-admin recipient only their organization;
- the Late chip says who sees it (escalation)."""
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.change import ChangeAssessment, ChangeChangelog, ChangeRequest
from app.models.entities import Organization, Plant, Project, User
from app.models.notification import Notification
from app.models.workflow import Department
from app.services import cm_switches, due_rules, ecr_mail
from tests.test_ecr_solid_mail import switch_on
from app.services.notification_service import NotificationService
from app.services.notification_sweep import escalated, run_notification_sweep, sweep_once
from tests.test_ecr_solid_tasks import _as, _create, _set, _tasks, team  # noqa: F401
from tests.test_ecr_solid_gates import admin, depts, people  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _change(s, seed, number, **kw):
    c = ChangeRequest(change_number=number, title="t", reason="r",
                      change_type="physical_part", project_id=seed["project_id"],
                      raised_by=seed["admin_id"], **kw)
    s.add(c)
    await s.flush()
    return c


async def _dept(s, name="Process Engineer"):
    d = Department(name=name, flow_type="action", is_active=True)
    s.add(d)
    await s.flush()
    return d


async def _notes(s, **where):
    q = select(Notification)
    for k, v in where.items():
        q = q.where(getattr(Notification, k) == v)
    return (await s.execute(q)).scalars().all()


# ---------------------------------------------------------------------------
# The running loop saves what it sends
# ---------------------------------------------------------------------------
async def test_sweep_once_commits_its_notices(session_factory, seed):
    async with session_factory() as s:
        c = await _change(s, seed, "C-R-1", lead_id=seed["admin_id"],
                          customer_relevant=True,
                          required_by_date=datetime.utcnow() - timedelta(days=1))
        await s.commit()
        cid = c.id
    counts = await sweep_once(session_factory)    # no commit in the test
    assert counts["deadline_overdue"] == 1
    async with session_factory() as fresh:
        assert await _notes(fresh, user_id=seed["admin_id"], kind="deadline_overdue",
                            subject_key=f"chg:{cid}:overdue")


# ---------------------------------------------------------------------------
# One notice per item, read or not; only the immediate class is mailed
# ---------------------------------------------------------------------------
async def test_a_read_late_notice_is_not_sent_again(session_factory, seed, monkeypatch):
    switch_on(monkeypatch)
    sent = []
    now = datetime.utcnow()
    async with session_factory() as s:
        d = await _dept(s)
        c = await _change(s, seed, "C-R-2", lead_id=seed["admin_id"])
        a = ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                             rasic_letter="R", owner_id=seed["engineer_id"],
                             due_date=now - timedelta(days=9))
        s.add(a); await s.commit()
        await run_notification_sweep(s); await s.commit()
        first = await _notes(s, kind="overdue")
        assert {n.user_id for n in first} == {seed["engineer_id"], seed["admin_id"]}
        assert [n.title for n in first if n.user_id == seed["engineer_id"]] \
            == ["Assessment late"]
        for n in first:
            n.is_read = True
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        assert len(await _notes(s, kind="overdue")) == len(first)   # no repeat
        # a late notice is a badge: never mailed
        await run_notification_sweep(s)
        for n in await _notes(s, kind="overdue"):
            n.is_read = False
        await s.commit()
        await ecr_mail.send_pending(s, sender=sent.append)
    # only the involved people's daily digest goes out, no late notice
    assert [m.subject for m in sent if "late" in m.subject.lower()] == []
    assert all(m.subject.startswith("Your changes today") for m in sent)


async def test_only_immediate_notices_are_mailed(session_factory, seed, monkeypatch):
    switch_on(monkeypatch)
    sent = []
    eng = seed["engineer_id"]
    async with session_factory() as s:
        await NotificationService.notify_once(
            s, [eng], kind="deviation_pending", subject_key="dev:1",
            title="Decision needed", link="/changes/1")
        await NotificationService.notify_once(
            s, [eng], kind="due_soon", subject_key="task:1:due_soon", title="Task due today")
        await NotificationService.notify_once(
            s, [eng], kind="stage_entered", subject_key="chg:1:in_validation",
            title="Validation started")
        await NotificationService.notify_users(
            s, [eng], "Assessment task: CR-1",
            "Your department has an assessment to give.\n"
            "Info: you are backup here, main: Sam.")
        await s.commit()
        # Christoph 2026-11-09: informative notices (stage started) are
        # mailed too, the informed in CC; reminders and backup copies stay badges
        assert await ecr_mail.send_pending(s, sender=sent.append) == 2
        rows = (await s.execute(select(Notification))).scalars().all()
        assert all(r.mailed_at is not None for r in rows)    # stamped, never retried
    assert [m.subject for m in sent] == ["Decision needed", "Validation started"]


# ---------------------------------------------------------------------------
# One lateness test
# ---------------------------------------------------------------------------
async def test_friday_due_is_not_late_over_the_weekend():
    due = datetime(2026, 10, 16, 10, 0)              # a Friday
    assert due.weekday() == 4
    cases = [(datetime(2026, 10, 17, 11, 0), False),  # Sat
             (datetime(2026, 10, 18, 11, 0), False),  # Sun
             (datetime(2026, 10, 19, 9, 0), False),   # Mon morning
             (datetime(2026, 10, 19, 11, 0), True)]   # Mon after due + 1 wd
    for now, want in cases:
        assert escalated(due, now) is want, now
        assert due_rules.is_late(due, now) is want    # My Tasks agrees


async def test_switch_off_escalates_at_the_due_date(monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    due = datetime(2026, 10, 16, 10, 0)
    assert escalated(due, datetime(2026, 10, 16, 11, 0)) is True
    assert escalated(due, datetime(2026, 10, 16, 9, 0)) is False


async def test_owned_unlinked_assessment_is_reminded_on_its_due_date(session_factory, seed):
    now = datetime.utcnow()
    end_of_today = now.replace(hour=23, minute=59, second=0, microsecond=0)
    async with session_factory() as s:
        d = await _dept(s)
        c = await _change(s, seed, "C-R-3")
        s.add_all([
            ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                             rasic_letter="R", owner_id=seed["engineer_id"],
                             due_date=end_of_today),
            # negative: unowned, or due later, is not reminded
            ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                             rasic_letter="R", due_date=end_of_today),
            ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                             rasic_letter="R", owner_id=seed["admin_id"],
                             due_date=end_of_today + timedelta(days=3))])
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        got = await _notes(s, kind="due_soon")
        assert [(n.user_id, n.title) for n in got] == [
            (seed["engineer_id"], "Assessment due today")]


# ---------------------------------------------------------------------------
# Read-only people get no row they could not act on (R18, R24)
# ---------------------------------------------------------------------------
async def _viewer(session_factory, seed, username="ro.approver"):
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=username,
                 email=f"{username}@test.io", full_name="Read Only",
                 hashed_password=get_password_hash("x-secret-123"),
                 role="viewer", is_active=True, mfa_enabled=False)
        s.add(u); await s.commit()
        return u.id


async def test_read_only_approver_is_skipped_for_the_fallback(
        client, seed, team, session_factory, monkeypatch):
    from tests.conftest import login
    await _viewer(session_factory, seed)
    monkeypatch.setattr(get_settings(), "internal_approvers", "ro.approver")
    dev = await _as(client, "Development")
    cid = await _create(client, dev, seed, customer_relevant=False)
    await _set(session_factory, cid, status="costing")
    viewer = await login(client, "ro.approver@test.io", admin=False)
    assert not await _tasks(client, viewer, cid, "internal_approval")
    res = await client.get(f"/api/v1/changes/{cid}/my-actions", headers=viewer)
    assert res.status_code == 200, res.text
    assert "internal_approval" not in [a["kind"] for a in res.json()["actions"]]
    # the Project Management fallback decides, and may
    pm = await _as(client, "Project Manager")
    assert len(await _tasks(client, pm, cid, "internal_approval")) == 1


async def test_read_only_lead_gets_no_move_on_row(client, seed, team, session_factory):
    from tests.conftest import login
    vid = await _viewer(session_factory, seed, "ro.lead")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="released", lead_id=vid)
    assert not await _tasks(client, await login(client, "ro.lead@test.io", admin=False),
                            cid, "advance")


# ---------------------------------------------------------------------------
# A row owed mid-status is due from when it became owed (C20)
# ---------------------------------------------------------------------------
async def _entered_status_days_ago(session_factory, cid, days, by):
    async with session_factory() as s:
        s.add(ChangeChangelog(change_id=cid, action="status_changed",
                              field_name="status", action_description="entered",
                              performed_by=by,
                              performed_at=datetime.utcnow() - timedelta(days=days)))
        await s.commit()


async def test_internal_approval_is_due_from_the_last_costing_finalized(
        client, seed, team, session_factory):
    dev = await _as(client, "Development")
    cid = await _create(client, dev, seed, customer_relevant=False)
    await _set(session_factory, cid, status="costing")
    await _entered_status_days_ago(session_factory, cid, 10, seed["admin_id"])
    async with session_factory() as s:
        a = ChangeAssessment(change_id=cid, department_id=team["dept"]["Development"],
                             status="submitted", rasic_letter="R", verdict="feasible")
        a.details = json.dumps({"costing_finalized_at": datetime.utcnow().isoformat()})
        s.add(a); await s.commit()
    pm = await _as(client, "Project Manager")
    row = (await _tasks(client, pm, cid, "internal_approval"))[0]
    assert row["late"] is False and row["overdue"] is False


async def test_move_on_is_due_from_when_the_change_last_moved(
        client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="released",
               lead_id=team["user"]["Project Manager"])
    await _entered_status_days_ago(session_factory, cid, 10, seed["admin_id"])
    pm = await _as(client, "Project Manager")
    rows = await _tasks(client, pm, cid, "advance")
    # the create's own changelog entry is today: owed since then
    assert rows and rows[0]["late"] is False
    assert rows[0]["label"] == "Close change"       # the Next step's own verb
    async with session_factory() as s:
        for e in (await s.execute(select(ChangeChangelog).where(
                ChangeChangelog.change_id == cid))).scalars().all():
            e.performed_at = datetime.utcnow() - timedelta(days=10)
        await s.commit()
    assert (await _tasks(client, pm, cid, "advance"))[0]["late"] is True


async def test_re_sign_is_due_from_the_newer_offer(client, seed, team, session_factory):
    from app.models.change_offer import ChangeOffer
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    old = datetime.utcnow() - timedelta(days=20)
    await _set(session_factory, cid, status="in_validation", customer_response="accepted",
               customer_response_at=old)
    async with session_factory() as s:
        o = ChangeOffer(change_id=cid, version=1, status="sent",
                        sent_at=datetime.utcnow(), created_by=seed["admin_id"])
        s.add(o); await s.commit()
    pm = await _as(client, "Project Manager")
    row = (await _tasks(client, pm, cid, "sign_off"))[0]
    assert row["late"] is False


# ---------------------------------------------------------------------------
# Sign-off rows follow the switches (R24/R30)
# ---------------------------------------------------------------------------
async def test_sign_off_rows_follow_the_switches(
        client, seed, team, session_factory, monkeypatch):
    from app.models.change_offer import ChangeOffer
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    async with session_factory() as s:
        o1 = ChangeOffer(change_id=cid, version=1, status="sent",
                         sent_at=datetime.utcnow() - timedelta(days=3),
                         created_by=seed["admin_id"])
        o2 = ChangeOffer(change_id=cid, version=2, status="sent",
                         sent_at=datetime.utcnow(), created_by=seed["admin_id"])
        s.add_all([o1, o2]); await s.commit()
        o1_id = o1.id
    await _set(session_factory, cid, status="quoted", customer_response="accepted",
               customer_response_at=datetime.utcnow(),
               pm_signed_by=team["user"]["Project Manager"],
               pm_signed_at=datetime.utcnow(), pm_signed_offer_id=o1_id)
    pm = await _as(client, "Project Manager")
    # bound to the latest offer: v1's signature does not count for v2
    assert [r["offer_version"] for r in await _tasks(client, pm, cid, "sign_off")] == [2]
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    assert not await _tasks(client, pm, cid, "sign_off")   # a signature is enough
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", True)
    await _set(session_factory, cid, status="approved")
    assert not await _tasks(client, pm, cid, "sign_off")   # no sign button here
    await _set(session_factory, cid, status="in_validation")
    assert await _tasks(client, pm, cid, "sign_off")       # HARD #9 at release
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    assert not await _tasks(client, pm, cid, "sign_off")   # release does not check


# ---------------------------------------------------------------------------
# Digest scope and the Late chip's promise
# ---------------------------------------------------------------------------
async def test_digest_shows_a_non_admin_only_their_organization(
        session_factory, seed, monkeypatch):
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "admin,deputy")
    now = datetime.utcnow()
    async with session_factory() as s:
        org = Organization(name="Other", code="other", is_active=True)
        s.add(org); await s.flush()
        plant = Plant(organization_id=org.id, name="P2", code="p2", location="US",
                      is_active=True)
        s.add(plant); await s.flush()
        s.add(Project(plant_id=plant.id, name="P2", code="p2", status="active"))
        deputy = User(organization_id=org.id, username="deputy", email="deputy@test.io",
                      full_name="Deputy", hashed_password="x", role="engineer",
                      is_active=True, mfa_enabled=False)
        s.add(deputy)
        await _change(s, seed, "C-R-9", customer_relevant=True, status="quoting",
                      created_at=now - timedelta(days=10))
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        got = await _notes(s, kind="overdue_digest")
        assert [n.user_id for n in got] == [seed["admin_id"]]   # never the deputy
        assert "C-R-9" in got[0].body


async def test_late_rows_say_who_sees_them(client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, created_at=datetime.utcnow() - timedelta(days=10))
    row = (await _tasks(client, sales, cid, "kickoff"))[0]
    assert row["late"] is True and row["escalation"] == "digest"
    await _set(session_factory, cid, status="released",
               lead_id=team["user"]["Project Manager"])
    row = (await _tasks(client, await _as(client, "Project Manager"), cid, "advance"))[0]
    assert row["escalation"] is None      # flagged for its owner only


async def test_internal_change_has_no_quote_deadline():
    from types import SimpleNamespace
    c = SimpleNamespace(required_by_date=datetime(2026, 11, 2), quoted_at=None,
                        release_due_date=None, customer_relevant=False)
    assert due_rules.deadline_of(c) == (None, None)


# ---------------------------------------------------------------------------
# "Needs you" for a concession: Quality's decision, not Sales' wait
# ---------------------------------------------------------------------------
async def test_concession_needs_only_the_quality_decider(
        client, admin, seed, depts, people, session_factory):
    from tests.test_ecr_solid_gates import _change as _gate_change, _concession, _failed_weight
    cid = await _gate_change(client, admin, seed, session_factory, "in_validation",
                             customer=False)
    check_id = await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    await _concession(session_factory, cid, check_id, people["Sales"][0])

    async def rows(auth):
        return [t for t in await _tasks(client, auth, cid)
                if t["kind"] == "validation_issue_customer"]
    quality = await rows(people["Quality"][1])
    assert quality and all(t["needs_you"] for t in quality)
    # negative: an internal change has no customer to ask: Sales gets no row
    assert await rows(people["Sales"][1]) == []


async def test_customer_concession_sales_waits_then_quality_decides(
        client, admin, seed, depts, people, session_factory):
    """A customer change: until the customer's mail is filed Sales owes the
    ask (a plain task, not Needs you) and Quality has nothing to decide; once
    it is filed Sales' part ends and Quality decides (Needs you)."""
    from app.models.change import ChangeAttachment
    from tests.test_ecr_solid_gates import _change as _gate_change, _concession, _failed_weight
    cid = await _gate_change(client, admin, seed, session_factory, "in_validation",
                             customer=True)
    check_id = await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    iid = await _concession(session_factory, cid, check_id, people["Sales"][0], mail=False)

    async def rows(auth):
        return [t for t in await _tasks(client, auth, cid)
                if t["kind"] == "validation_issue_customer"]
    sales = await rows(people["Sales"][1])
    assert sales and not any(t["needs_you"] for t in sales)
    # negative: nothing for Quality to decide before the mail is filed
    assert not any(t["needs_you"] for t in await rows(people["Quality"][1]))
    async with session_factory() as s:
        s.add(ChangeAttachment(change_id=cid, filename="yes.msg", stored_path="x",
                               content_type="application/vnd.ms-outlook",
                               size_bytes=1, sha256="0" * 64, kind="customer_email",
                               validation_issue_id=iid, uploaded_by=people["Sales"][0]))
        await s.commit()
    quality = await rows(people["Quality"][1])
    assert quality and all(t["needs_you"] for t in quality)
    assert await rows(people["Sales"][1]) == []
