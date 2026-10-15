"""ECR-solid lane L3, review loop 2 (spec §0 My Tasks, one escalation rule,
notifications):

- a sign-off row only where the screen offers the sign button (quoted after
  the customer's yes, in_validation), and the sign-off endpoint refuses a
  change outside quoted..in_validation;
- a read-only person gets no row at all; a read-only lead leaves the onward
  hop to Project Management;
- a pending routing change and a 'not feasible' answer are somebody's task;
- one bad recipient does not hold the mail outbox; kind-less FYI is a badge;
- a deadline alert names its deadline, a release alert after a quote alert
  still goes out;
- computed rows (costing, sign-off, internal approval, overrides) follow the
  one escalation rule: reminder on the due date, lead + digest when late;
- the daily digest for involved people (lead, raiser, Sales owner)."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.change import ChangeRequest
from app.models.notification import Notification
from app.services import cm_switches
from tests.conftest import login
from tests.test_ecr_solid_tasks import _as, _create, _set, _tasks, team  # noqa: F401
from tests.test_ecr_solid_l3_review import _viewer

pytestmark = pytest.mark.asyncio


async def _notes(s, **where):
    q = select(Notification)
    for k, v in where.items():
        q = q.where(getattr(Notification, k) == v)
    return (await s.execute(q)).scalars().all()


# ---------------------------------------------------------------------------
# Sign-off rows only where a sign button is (R5, R24), endpoint by status (R25)
# ---------------------------------------------------------------------------
async def test_change_approved_without_signatures_has_no_sign_row_until_validation(
        client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="approved", customer_response="accepted",
               customer_response_at=datetime.utcnow())
    pm, quality = await _as(client, "Project Manager"), await _as(client, "Quality")
    for st in ("approved", "in_implementation"):
        await _set(session_factory, cid, status=st)
        assert not await _tasks(client, pm, cid, "sign_off")
        assert not await _tasks(client, quality, cid, "sign_off")
    await _set(session_factory, cid, status="in_validation")
    assert [r["side"] for r in await _tasks(client, pm, cid, "sign_off")] == ["pm"]
    # the row has its button: Why blocked lists the release sign-offs
    res = await client.get(f"/api/v1/changes/{cid}", headers=pm)
    keys = [i["key"] for i in (res.json().get("next_step") or {}).get("items", [])]
    assert "release_signoffs" in keys


@pytest.mark.parametrize("status", ["captured", "scoping", "closed", "cancelled"])
async def test_sign_off_is_refused_outside_quote_to_validation(
        client, seed, team, session_factory, status):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status=status)
    pm = await _as(client, "Project Manager")
    res = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"},
                            headers=pm)
    assert res.status_code == 400, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).pm_signed_by is None


async def test_sign_off_allowed_in_validation(client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="in_validation")
    pm = await _as(client, "Project Manager")
    res = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"},
                            headers=pm)
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# A read-only person gets no row; a read-only lead leaves the hop to PM (R18/R24)
# ---------------------------------------------------------------------------
async def test_read_only_lead_gets_no_rows_and_pm_takes_the_hop(
        client, seed, team, session_factory):
    from app.services import mother_plants as mp
    vid = await _viewer(session_factory, seed, "ro.lead2")
    sales = await _as(client, "Sales")
    # a mother-plant change at scoping: before, its lead got "Send information"
    info = await _create(client, sales, seed, "mp")
    await _set(session_factory, info, status="scoping", origin=mp.MOTHER_PLANT,
               lead_id=vid)
    hop = await _create(client, sales, seed, "hop")
    await _set(session_factory, hop, status="released", lead_id=vid)
    viewer = await login(client, "ro.lead2@test.io", admin=False)
    assert await _tasks(client, viewer) == []                # nothing it could do
    pm = await _as(client, "Project Manager")
    assert len(await _tasks(client, pm, hop, "advance")) == 1  # PM's now
    assert await _tasks(client, pm, info, "info_send")
    # negative: a lead who can act keeps the hop; Sales never gets it
    await _set(session_factory, hop, lead_id=team["user"]["Development"])
    assert not await _tasks(client, pm, hop, "advance")
    assert len(await _tasks(client, await _as(client, "Development"), hop, "advance")) == 1
    assert not await _tasks(client, sales, hop, "advance")


async def test_inactive_lead_leaves_the_hop_to_pm(client, seed, team, session_factory):
    from app.models.entities import User
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="released",
               lead_id=team["user"]["Development"])
    async with session_factory() as s:
        (await s.get(User, team["user"]["Development"])).is_active = False
        await s.commit()
    pm = await _as(client, "Project Manager")
    assert len(await _tasks(client, pm, cid, "advance")) == 1


# ---------------------------------------------------------------------------
# A pending routing change and a 'not feasible' answer are tasks (R18, C3 b)
# ---------------------------------------------------------------------------
async def _pending_routing(session_factory, cid, proposer):
    from app.models.change import ChangeRouting
    async with session_factory() as s:
        s.add(ChangeRouting(change_id=cid, has_deviation=True,
                            deviation_status="pending_approval",
                            deviation_proposed_by=proposer))
        await s.commit()


async def test_pending_routing_change_is_the_deciders_task(
        client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    u = team["user"]
    await _set(session_factory, cid, status="in_assessment", lead_id=u["Development"])
    await _pending_routing(session_factory, cid, u["Tool Engineer"])
    dev, pm = await _as(client, "Development"), await _as(client, "Project Manager")
    rows = await _tasks(client, dev, cid, "routing_deviation_decision")
    assert len(rows) == 1 and rows[0]["needs_you"] is True
    assert rows[0]["target_tab"] == "assessments"
    # negative: the proposer, Project Management (the lead decides), Sales
    assert not await _tasks(client, await _as(client, "Tool Engineer"), cid,
                            "routing_deviation_decision")
    assert not await _tasks(client, pm, cid, "routing_deviation_decision")
    assert not await _tasks(client, sales, cid, "routing_deviation_decision")
    # the lead asked: Project Management decides, the lead does not
    async with session_factory() as s:
        from app.models.change import ChangeRouting
        r = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == cid))).scalar_one()
        r.deviation_proposed_by = u["Development"]
        await s.commit()
    assert not await _tasks(client, dev, cid, "routing_deviation_decision")
    assert len(await _tasks(client, pm, cid, "routing_deviation_decision")) == 1


async def test_read_only_lead_leaves_the_routing_decision_to_pm(
        client, seed, team, session_factory):
    vid = await _viewer(session_factory, seed, "ro.lead3")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="in_assessment", lead_id=vid)
    await _pending_routing(session_factory, cid, team["user"]["Tool Engineer"])
    pm = await _as(client, "Project Manager")
    assert len(await _tasks(client, pm, cid, "routing_deviation_decision")) == 1
    # and the endpoint lets Project Management decide (no dead end)
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation/reject",
                            json={"reason": "not needed here"}, headers=pm)
    assert res.status_code != 403 and "Only the change lead" not in res.text, res.text


async def test_not_feasible_answer_is_the_leads_decision(
        client, seed, team, session_factory):
    from app.models.change import ChangeAssessment, ChangeTransitionDeviation
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    u = team["user"]
    await _set(session_factory, cid, status="in_assessment",
               lead_id=u["Project Manager"])
    async with session_factory() as s:
        s.add(ChangeAssessment(change_id=cid, department_id=team["dept"]["Tool Engineer"],
                               status="submitted", rasic_letter="R",
                               verdict="not_feasible", submitted_at=datetime.utcnow()))
        await s.commit()
    pm = await _as(client, "Project Manager")
    rows = await _tasks(client, pm, cid, "not_feasible")
    assert len(rows) == 1
    assert rows[0]["hint"].startswith("Tool Engineer says not feasible")
    assert not await _tasks(client, pm, cid, "advance")
    # negative: the department that answered, Sales
    assert not await _tasks(client, await _as(client, "Tool Engineer"), cid, "not_feasible")
    assert not await _tasks(client, sales, cid, "not_feasible")
    # an override asked for the rule: the decider's row takes over
    async with session_factory() as s:
        s.add(ChangeTransitionDeviation(
            change_id=cid, to_status="costing", reason="customer accepts the risk",
            guard_key="not_feasible", proposed_by=u["Project Manager"],
            status="pending"))
        await s.commit()
    assert not await _tasks(client, pm, cid, "not_feasible")


# ---------------------------------------------------------------------------
# Mail: one bad recipient does not hold the outbox; kind-less FYI is a badge
# ---------------------------------------------------------------------------
@pytest.fixture
def smtp_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_enabled", True)
    monkeypatch.setattr(s, "mail_default_domain", "")
    return []


async def test_refused_recipient_is_skipped_and_the_next_mail_goes(
        session_factory, seed, smtp_on):
    import smtplib
    from app.services import mail_outbox
    from app.services.notification_service import NotificationService

    def sender(msg):
        if msg["Subject"] == "first":
            raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such user")})
        smtp_on.append(msg)
    async with session_factory() as s:
        for title in ("first", "second"):
            await NotificationService.notify_users(s, [seed["engineer_id"]], title,
                                                   kind="task_assigned")
        await s.commit()
        assert await mail_outbox.send_pending(s, sender=sender) == 1
        assert all(n.mailed_at is not None for n in await _notes(s))  # no retry loop
    assert [m["Subject"] for m in smtp_on] == ["second"]


async def test_relay_down_stops_and_retries_next_run(session_factory, seed, smtp_on):
    import smtplib
    from app.services import mail_outbox
    from app.services.notification_service import NotificationService

    def down(msg):
        raise smtplib.SMTPServerDisconnected("gone")
    async with session_factory() as s:
        await NotificationService.notify_users(s, [seed["engineer_id"]], "x",
                                               kind="task_assigned")
        await s.commit()
        assert await mail_outbox.send_pending(s, sender=down) == 0
        assert (await _notes(s))[0].mailed_at is None
        assert await mail_outbox.send_pending(s, sender=smtp_on.append) == 1


async def test_bare_hub_username_gets_the_mail_domain(
        session_factory, seed, smtp_on, monkeypatch):
    from app.models.entities import User
    from app.services import mail_outbox
    from app.services.notification_service import NotificationService
    async with session_factory() as s:
        (await s.get(User, seed["engineer_id"])).email = "christoph.demmler"
        await NotificationService.notify_users(s, [seed["engineer_id"]], "a",
                                               kind="task_assigned")
        await s.commit()
        # no domain configured: no address, stamped, nothing sent
        assert await mail_outbox.send_pending(s, sender=smtp_on.append) == 0
        monkeypatch.setattr(get_settings(), "mail_default_domain", "ktx.example")
        await NotificationService.notify_users(s, [seed["engineer_id"]], "b",
                                               kind="task_assigned")
        await s.commit()
        assert await mail_outbox.send_pending(s, sender=smtp_on.append) == 1
    assert smtp_on[0]["To"] == "christoph.demmler@ktx.example"


async def test_kind_less_fyi_is_not_mailed(session_factory, seed, smtp_on):
    from app.services import mail_outbox
    from app.services.notification_service import NotificationService
    async with session_factory() as s:
        await NotificationService.notify_users(
            s, [seed["engineer_id"]], "Cost carrier changed: CR-1")
        await NotificationService.notify_users(
            s, [seed["engineer_id"]], "Overdue lesson action (94d): L")
        await s.commit()
        assert await mail_outbox.send_pending(s, sender=smtp_on.append) == 0
    assert smtp_on == []


# ---------------------------------------------------------------------------
# Deadline alerts name their deadline; a quote alert never hides a release one
# ---------------------------------------------------------------------------
async def test_release_alert_after_a_quote_alert(session_factory, seed):
    from app.services.notification_sweep import run_notification_sweep
    now = datetime.utcnow()
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-DL-1", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                          customer_relevant=True, status="quoting",
                          required_by_date=now - timedelta(days=2))
        s.add(c); await s.commit()
        await run_notification_sweep(s); await s.commit()
        quote = await _notes(s, kind="deadline_overdue")
        assert [n.title for n in quote] == ["Quote deadline overdue: C-DL-1"]
        assert quote[0].body.startswith("Quote due ")
        quote[0].is_read = True
        c.status, c.quoted_at = "approved", now - timedelta(days=1)
        c.release_due_date = now - timedelta(days=1)
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        got = await _notes(s, kind="deadline_overdue")
        assert len(got) == 2
        rel = [n for n in got if n.id != quote[0].id][0]
        assert rel.title == "Release deadline overdue: C-DL-1"
        assert rel.body.startswith("Release due ")
        await run_notification_sweep(s); await s.commit()
        assert len(await _notes(s, kind="deadline_overdue")) == 2   # once per item
