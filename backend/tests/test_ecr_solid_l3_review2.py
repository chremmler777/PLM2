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
    from tests.test_ecr_solid_mail import switch_on
    s = get_settings()
    switch_on(monkeypatch)
    monkeypatch.setattr(s, "mail_default_domain", "")
    return []


async def test_refused_recipient_is_skipped_and_the_next_mail_goes(
        session_factory, seed, smtp_on):
    from app.services import ecr_mail
    from app.services.notification_service import NotificationService

    def sender(msg):
        if msg.subject == "first":   # graph_send's error for a bad recipient
            raise RuntimeError("Graph sendMail 400: ErrorInvalidRecipients")
        smtp_on.append(msg)
    async with session_factory() as s:
        for title in ("first", "second"):
            await NotificationService.notify_users(s, [seed["engineer_id"]], title,
                                                   kind="task_assigned")
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=sender) == 1
        assert all(n.mailed_at is not None for n in await _notes(s))  # no retry loop
    assert [m.subject for m in smtp_on] == ["second"]


async def test_relay_down_stops_and_retries_next_run(session_factory, seed, smtp_on):
    import httpx
    from app.services import ecr_mail
    from app.services.notification_service import NotificationService

    def down(msg):
        raise httpx.ConnectError("gone")
    async with session_factory() as s:
        await NotificationService.notify_users(s, [seed["engineer_id"]], "x",
                                               kind="task_assigned")
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=down) == 0
        assert (await _notes(s))[0].mailed_at is None
        assert await ecr_mail.send_pending(s, sender=smtp_on.append) == 1


async def test_bare_hub_username_gets_the_mail_domain(
        session_factory, seed, smtp_on, monkeypatch):
    from app.models.entities import User
    from app.services import ecr_mail
    from app.services.notification_service import NotificationService
    async with session_factory() as s:
        (await s.get(User, seed["engineer_id"])).email = "christoph.demmler"
        await NotificationService.notify_users(s, [seed["engineer_id"]], "a",
                                               kind="task_assigned")
        await s.commit()
        # no domain configured: no address, stamped, nothing sent
        assert await ecr_mail.send_pending(s, sender=smtp_on.append) == 0
        monkeypatch.setattr(get_settings(), "mail_default_domain", "ktx.example")
        await NotificationService.notify_users(s, [seed["engineer_id"]], "b",
                                               kind="task_assigned")
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=smtp_on.append) == 1
    assert smtp_on[0].to == ["christoph.demmler@ktx.example"]


async def test_kind_less_fyi_is_not_mailed(session_factory, seed, smtp_on):
    from app.services import ecr_mail
    from app.services.notification_service import NotificationService
    async with session_factory() as s:
        await NotificationService.notify_users(
            s, [seed["engineer_id"]], "Cost carrier changed: CR-1")
        await NotificationService.notify_users(
            s, [seed["engineer_id"]], "Overdue lesson action (94d): L")
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=smtp_on.append) == 0
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


# ---------------------------------------------------------------------------
# Computed rows follow the one escalation rule (spec §0, C20/C27)
# ---------------------------------------------------------------------------
async def _owing_costing(session_factory, team, cid, submitted_at):
    from app.models.change import ChangeAssessment
    async with session_factory() as s:
        s.add(ChangeAssessment(change_id=cid, department_id=team["dept"]["Tool Engineer"],
                               status="submitted", rasic_letter="R", verdict="feasible",
                               submitted_at=submitted_at))
        await s.commit()


async def test_late_costing_reaches_the_lead_the_group_and_the_digest(
        client, seed, team, session_factory, monkeypatch):
    from app.services.notification_sweep import run_notification_sweep
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "admin")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "costing late")
    pm_id = team["user"]["Project Manager"]
    await _set(session_factory, cid, status="in_assessment", lead_id=pm_id)
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=10))
    tool = await _as(client, "Tool Engineer")
    row = (await _tasks(client, tool, cid, "costing_input"))[0]
    assert row["late"] is True and row["escalation"] == "lead_digest"
    async with session_factory() as s:
        await run_notification_sweep(s); await s.commit()
        lead = await _notes(s, user_id=pm_id, kind="overdue")
        assert [n.title for n in lead] == [
            f"Late: Costing input: Tool Engineer on {row['change_number']}"]
        assert not await _notes(s, user_id=team["user"]["Tool Engineer"], kind="due_soon")
        digest = (await _notes(s, kind="overdue_digest"))[0]
        assert "Costing input: Tool Engineer (Tool Engineer, due" in digest.body
        await run_notification_sweep(s); await s.commit()
        assert len(await _notes(s, user_id=pm_id, kind="overdue")) == 1   # once
    res = await client.get("/api/v1/changes/my-escalations",
                           headers=await _as(client, "Project Manager"))
    assert res.status_code == 200, res.text
    assert [e["label"] for e in res.json() if e["kind"] == "costing_input"] == [
        "Costing input: Tool Engineer"]


async def test_costing_due_today_reminds_the_department_not_the_lead(
        client, seed, team, session_factory):
    from app.services import due_rules
    from app.services.notification_sweep import run_notification_sweep
    now = datetime.utcnow()
    start = due_rules.sub_wd(now, 2)
    if due_rules.add_wd(start, 2).date() != now.date():
        pytest.skip("weekend: no working day due today")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "costing today")
    pm_id = team["user"]["Project Manager"]
    await _set(session_factory, cid, status="in_assessment", lead_id=pm_id)
    await _owing_costing(session_factory, team, cid, start)
    async with session_factory() as s:
        await run_notification_sweep(s); await s.commit()
        reminded = {n.user_id for n in await _notes(s, kind="due_soon")}
        assert reminded == {team["user"]["Tool Engineer"], team["user"]["tool2"]}
        assert not await _notes(s, user_id=pm_id, kind="overdue")


async def test_late_rows_without_a_lead_or_digest_say_so(
        client, seed, team, session_factory, monkeypatch):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "no lead")
    await _set(session_factory, cid, status="in_assessment", lead_id=None)
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=10))
    tool = await _as(client, "Tool Engineer")
    # A6-03: no lead, so Project Management sees it (and the digest)
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["escalation"] == "pm_digest"
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["escalation"] == "pm"
    await _set(session_factory, cid, lead_id=team["user"]["Project Manager"])
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["escalation"] == "lead"


async def test_late_sign_off_and_override_reach_the_lead(client, seed, team, session_factory):
    from app.models.change import ChangeTransitionDeviation
    from app.services.notification_sweep import run_notification_sweep
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "sign late")
    dev_id = team["user"]["Development"]
    old = datetime.utcnow() - timedelta(days=10)
    await _set(session_factory, cid, status="quoted", customer_response="accepted",
               customer_response_at=old, lead_id=dev_id)
    async with session_factory() as s:
        # the lead asked: Project Management decides, the lead hears it is late
        s.add(ChangeTransitionDeviation(change_id=cid, to_status="approved", reason="r",
                                        proposed_by=dev_id, status="pending",
                                        proposed_at=old))
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        titles = sorted(n.title for n in await _notes(s, user_id=dev_id, kind="overdue"))
    assert any(t.startswith("Late: PM sign-off") for t in titles)
    assert any(t.startswith("Late: Quality sign-off") for t in titles)
    assert any(t.startswith("Late: Decide override #") for t in titles)


async def test_task_clock_floor_keeps_in_flight_rows_from_being_late(
        client, seed, team, session_factory, monkeypatch):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "in flight")
    await _set(session_factory, cid, status="in_assessment")
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=30))
    tool = await _as(client, "Tool Engineer")
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["late"] is True
    monkeypatch.setattr(get_settings(), "cm_task_clock_from",
                        datetime.utcnow().date().isoformat())
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["late"] is False


# ---------------------------------------------------------------------------
# The daily digest for the people involved (spec §0 Digest, §4)
# ---------------------------------------------------------------------------
async def test_involved_people_get_one_line_per_change_once_a_day(
        client, seed, team, session_factory, monkeypatch):
    from app.models.change import ChangeConcern
    from app.services.notification_sweep import run_notification_sweep
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "")
    u = team["user"]
    sales = await _as(client, "Sales")
    busy = await _create(client, sales, seed, "busy")
    quiet = await _create(client, sales, seed, "quiet")
    now = datetime.utcnow()
    await _set(session_factory, busy, status="in_assessment", lead_id=u["Project Manager"],
               sales_owner_id=u["Sales"], required_by_date=now - timedelta(days=1))
    await _set(session_factory, quiet, status="in_assessment", lead_id=u["Project Manager"],
               required_by_date=now + timedelta(days=60))
    async with session_factory() as s:
        s.add(ChangeConcern(change_id=busy, kind="needs_info", note="which grain?",
                            raised_by=u["Development"], answered_at=now - timedelta(hours=2),
                            answer_note="VW grain"))
        s.add(ChangeConcern(change_id=busy, kind="needs_info", note="volume?",
                            raised_by=u["Development"]))
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        got = await _notes(s, kind="change_digest")
        by_user = {n.user_id: n for n in got}
        # lead, raiser (Sales created it) and Sales owner: one each
        assert set(by_user) == {u["Project Manager"], u["Sales"]}
        body = by_user[u["Project Manager"]].body
        lines = body.splitlines()
        assert len(lines) == 1                       # the quiet change has no line
        assert "quote deadline" in lines[0] and "(overdue)" in lines[0]
        assert "1 answered since yesterday" in lines[0]
        assert "waiting on 1 answer" in lines[0]
        # once a day, read or not
        for n in got:
            n.is_read = True
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        assert len(await _notes(s, kind="change_digest")) == len(got)
    # negative: switch off, no digest
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    from app.services.change_digest import send_change_digest
    async with session_factory() as s:
        assert await send_change_digest(s, now=now + timedelta(days=1)) == 0


async def test_read_only_raiser_gets_no_digest(client, seed, team, session_factory):
    vid = await _viewer(session_factory, seed, "ro.raiser")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "ro")
    await _set(session_factory, cid, status="in_assessment", raised_by=vid,
               required_by_date=datetime.utcnow() - timedelta(days=1))
    from app.services.change_digest import send_change_digest
    async with session_factory() as s:
        await send_change_digest(s); await s.commit()
        assert not await _notes(s, kind="change_digest", user_id=vid)


# ---------------------------------------------------------------------------
# One selection of a change's tasks; other workflows keep their wording
# ---------------------------------------------------------------------------
async def test_part_revision_task_escalates_and_other_workflows_keep_their_words(
        session_factory, seed):
    from app.models.part import Part, PartRevision
    from app.models.workflow import Department, WfInstance, WfInstanceTask, WfTemplate
    from app.services.notification_sweep import run_notification_sweep
    old = datetime.utcnow() - timedelta(days=10)
    async with session_factory() as s:
        d = Department(name="Process Engineer", flow_type="action", is_active=True)
        t = WfTemplate(name="T", description="x", version=1, is_active=True, created_by=1)
        s.add_all([d, t]); await s.flush()
        c = ChangeRequest(change_number="C-PR-1", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                          status="in_implementation")
        s.add(c); await s.flush()
        part = Part(project_id=seed["project_id"], part_number="PR-1", name="p",
                    part_type="internal_mfg", created_by=seed["admin_id"],
                    updated_by=seed["admin_id"])
        s.add(part); await s.flush()
        rev = PartRevision(part_id=part.id, revision_name="B", originating_change_id=c.id,
                           phase="review",
                           created_by=seed["admin_id"])
        s.add(rev); await s.flush()
        own = WfInstance(template_id=t.id, part_revision_id=rev.id, status="active",
                         current_stage_order=1, started_by=seed["admin_id"])
        other = WfInstance(template_id=t.id, status="active", current_stage_order=1,
                           started_by=seed["admin_id"])
        s.add_all([own, other]); await s.flush()
        for inst in (own, other):
            s.add(WfInstanceTask(instance_id=inst.id, stage_order=1, department_id=d.id,
                                 rasic_letter="R", status="active", is_actionable=True,
                                 owner_id=seed["engineer_id"], due_date=old))
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        lead = await _notes(s, user_id=seed["admin_id"], kind="overdue")
        assert [n.title for n in lead] == ["Late: task on C-PR-1"]
        mine = sorted(n.title for n in await _notes(s, user_id=seed["engineer_id"],
                                                     kind="overdue"))
        # the change's task under the one rule; the other workflow as before
        assert mine == ["Task late", "Task overdue"]
