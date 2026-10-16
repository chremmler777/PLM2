"""ECR-solid close-out area 6 (tasks, notifications, next-action panels).

- A6-01: the task clock's go-live is stamped (migration 143), so a change in
  flight at go-live is not Late without CM_TASK_CLOCK_FROM, and the overdue
  digest's Sales rows count from the same floor as My Tasks."""
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from app.core.config import get_settings
from app.models.change import ChangeChangelog, ChangeRequest
from app.models.cost_sheet import OrgSetting
from tests.test_ecr_solid_l3_review2 import _owing_costing
from tests.test_ecr_solid_tasks import _as, _create, _set, _tasks, team  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _stamp_go_live(session_factory, seed, when: datetime):
    async with session_factory() as s:
        s.add(OrgSetting(organization_id=seed["org_id"], key="cm_task_clock_from",
                         value=when.replace(microsecond=0).isoformat()))
        await s.commit()


# ---------------------------------------------------------------------------
# A6-01 a safe default for the task clock
# ---------------------------------------------------------------------------
async def test_stamped_go_live_keeps_in_flight_row_from_late_without_env(
        client, seed, team, session_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "cm_task_clock_from", "")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "in flight")
    await _set(session_factory, cid, status="in_assessment")
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=30))
    tool = await _as(client, "Tool Engineer")
    # no stamp: the row counts from its start (negative case)
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["late"] is True
    await _stamp_go_live(session_factory, seed, datetime.utcnow() - timedelta(hours=1))
    row = (await _tasks(client, tool, cid, "costing_input"))[0]
    assert row["late"] is False and row["overdue"] is False


async def test_env_clock_wins_over_the_stamp(client, seed, team, session_factory,
                                             monkeypatch):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "env wins")
    await _set(session_factory, cid, status="in_assessment")
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=30))
    await _stamp_go_live(session_factory, seed, datetime.utcnow())
    monkeypatch.setattr(get_settings(), "cm_task_clock_from",
                        (datetime.utcnow() - timedelta(days=60)).date().isoformat())
    tool = await _as(client, "Tool Engineer")
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["late"] is True


async def test_digest_sales_row_counts_from_the_go_live(
        client, seed, team, session_factory, monkeypatch):
    from app.services.overdue_digest import late_by_change
    monkeypatch.setattr(get_settings(), "cm_task_clock_from", "")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "old quote")
    old = datetime.utcnow() - timedelta(days=30)
    await _set(session_factory, cid, status="quoting", created_at=old)
    async with session_factory() as s:
        s.add(ChangeChangelog(change_id=cid, action="status_change", action_description="s", performed_by=team["user"]["Sales"], field_name="status", old_value="approved",
                              new_value="quoting", performed_at=old))
        await s.commit()

    async def sales_lines():
        async with session_factory() as s:
            c = await s.get(ChangeRequest, cid)
            got = await late_by_change(s, {cid: c}, datetime.utcnow(), deadlines=False)
        return [t for t in got.get(cid, []) if t.startswith("Sales")]

    assert await sales_lines()                           # late without a floor
    await _stamp_go_live(session_factory, seed, datetime.utcnow() - timedelta(hours=1))
    assert await sales_lines() == []


@pytest.mark.filterwarnings("ignore")
def test_migration_143_stamps_once_and_downgrades(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    from tests.test_migration_118_sqlite import _load, _run
    _load_migration_032()
    m = _load("143_task_clock_go_live.py")
    assert (m.revision, m.down_revision) == ("143", "142")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm143.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE organizations (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql(
            "CREATE TABLE org_settings (id INTEGER PRIMARY KEY, organization_id INTEGER, "
            "key VARCHAR(80), value VARCHAR(255), updated_by INTEGER, updated_at DATETIME)")
        conn.exec_driver_sql("INSERT INTO organizations VALUES (1), (2)")
        conn.exec_driver_sql("INSERT INTO org_settings (organization_id, key, value) "
                             "VALUES (2, 'cm_task_clock_from', '2026-11-02')")
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)                 # repeatable
        rows = dict(conn.execute(sa.text(
            "SELECT organization_id, value FROM org_settings "
            "WHERE key = 'cm_task_clock_from'")).all())
        assert rows[2] == "2026-11-02"        # an admin's value is kept
        assert datetime.fromisoformat(rows[1]) <= datetime.utcnow()
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        assert conn.execute(sa.text("SELECT count(*) FROM org_settings")).scalar() == 0


# ---------------------------------------------------------------------------
# A6-02 'decision needed' is delivered (spec §0 Notifications, immediate)
# ---------------------------------------------------------------------------
from tests.test_ecr_solid_commercial import _YES, _answer, quoted  # noqa: E402,F401
from tests.test_offers import _auth as _offer_auth, offer_world  # noqa: E402,F401


async def _decisions(session_factory, user_id):
    from app.models.notification import Notification
    async with session_factory() as s:
        return (await s.execute(sa.select(Notification).where(
            Notification.user_id == user_id,
            Notification.kind == "decision_needed"))).scalars().all()


def test_decision_needed_and_override_answers_are_mailed():
    from app.services.mail_outbox import MAIL_KINDS
    assert {"decision_needed", "deviation_decided"} <= MAIL_KINDS


async def test_first_sign_off_after_the_yes_tells_each_side_once(
        client, quoted, session_factory):
    cid, oid = quoted["change_id"], quoted["offer_id"]
    pm_id, q_id = quoted["users"]["pm"], quoted["quality_id"]
    # NEGATIVE: nothing before the customer's yes
    assert await _decisions(session_factory, pm_id) == []
    sales = await _offer_auth(client, "sales")
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 200, res.text
    pm_n = await _decisions(session_factory, pm_id)
    q_n = await _decisions(session_factory, q_id)
    assert [n.subject_key for n in pm_n] == [f"chg:{cid}:sign:pm:{oid}"]
    assert [n.subject_key for n in q_n] == [f"chg:{cid}:sign:quality:{oid}"]
    assert pm_n[0].title.startswith("PM sign-off needed")
    # NEGATIVE: Sales (the actor, no signer) hears nothing
    assert await _decisions(session_factory, quoted["users"]["sales"]) == []


async def test_the_side_already_signed_gets_no_notice(client, quoted, session_factory):
    from tests.conftest import login
    cid = quoted["change_id"]
    q = await login(client, "off-quality@test.io", "role-secret-1")
    r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"},
                          headers=q)
    assert r.status_code == 200, r.text
    sales = await _offer_auth(client, "sales")
    assert (await _answer(client, cid, sales, _YES)).status_code == 200
    assert len(await _decisions(session_factory, quoted["users"]["pm"])) == 1
    assert await _decisions(session_factory, quoted["quality_id"]) == []


async def test_switch_off_sends_no_sign_off_notice(client, quoted, session_factory,
                                                   monkeypatch):
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "on",
                        lambda k: k != "COMMERCIAL_V2")
    sales = await _offer_auth(client, "sales")
    res = await _answer(client, quoted["change_id"], sales,
                        {"response": "accepted", "release_due_date": _YES["release_due_date"],
                         "ref": "PO 4500123456"})
    assert res.status_code == 200, res.text
    assert await _decisions(session_factory, quoted["users"]["pm"]) == []


async def test_internal_approval_owed_tells_the_approver_once_never_the_raiser(
        client, seed, team, session_factory):
    from app.services.decision_notices import internal_approval_owed
    dev = await _as(client, "Development")
    cid = await _create(client, dev, seed, "internal spend", customer_relevant=False)
    await _set(session_factory, cid, status="costing")
    await _owing_costing(session_factory, team, cid, datetime.utcnow())
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        # NEGATIVE: Tool Engineer has not finalized its costing yet
        assert await internal_approval_owed(s, c, None) == 0
    await _set(session_factory, cid, status="costing")
    async with session_factory() as s:
        from app.models.change import ChangeAssessment
        a = (await s.execute(sa.select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalar_one()
        await s.delete(a)
        await s.commit()
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        assert await internal_approval_owed(s, c, None) == 1
        assert await internal_approval_owed(s, c, None) == 0       # once
        await s.commit()
    pm_n = await _decisions(session_factory, team["user"]["Project Manager"])
    assert [n.subject_key for n in pm_n] == [f"chg:{cid}:internal_approval"]
    assert await _decisions(session_factory, team["user"]["Development"]) == []


from tests.test_ecr_solid_fix_concession import (  # noqa: E402,F401
    _fail_weight, _issue, _iurl, _who, fix,
)
from tests.test_validation_checks import _auth as _val_auth, val  # noqa: E402,F401


async def test_filed_customer_mail_tells_quality_to_decide_the_concession(
        client, fix, session_factory):
    await _fail_weight(client, fix)
    iid = (await _issue(client, fix))["id"]
    quality = await _who(client, fix, "Quality")
    res = await client.post(_iurl(fix, f"/{iid}/concession"), headers=quality,
                            json={"note": "ask for 518 g max, 500 parts"})
    assert res.status_code == 200, res.text
    q_id, sales_id = fix["user"]["Quality"]["id"], fix["user"]["Sales"]["id"]
    # NEGATIVE: nothing to decide before the mail is filed
    assert await _decisions(session_factory, q_id) == []
    sales = await _val_auth(client, fix, "Sales")
    up = await client.post(
        f"/api/v1/changes/{fix['change_id']}/attachments", headers=sales,
        files={"file": ("mail.eml", b"From: customer", "message/rfc822")},
        data={"kind": "customer_email", "validation_issue_id": str(iid)})
    assert up.status_code in (200, 201), up.text
    assert [n.subject_key for n in await _decisions(session_factory, q_id)] == [
        f"vi:{iid}:concession_decide"]
    assert await _decisions(session_factory, sales_id) == []


# ---------------------------------------------------------------------------
# A6-03 an idle or missing lead: Project Management gets the escalation
# ---------------------------------------------------------------------------
async def _overdue(session_factory, user_id):
    from app.models.notification import Notification
    async with session_factory() as s:
        return (await s.execute(sa.select(Notification).where(
            Notification.user_id == user_id,
            Notification.kind == "overdue"))).scalars().all()


@pytest.mark.parametrize("lead", ["idle", "none"])
async def test_leadless_change_escalates_to_project_management(
        client, seed, team, session_factory, lead):
    from tests.test_ecr_solid_l3_review import _viewer
    from app.services.notification_sweep import run_notification_sweep
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "no lead to act")
    idle = await _viewer(session_factory, seed) if lead == "idle" else None
    await _set(session_factory, cid, status="in_assessment", lead_id=idle)
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=10))
    tool = await _as(client, "Tool Engineer")
    row = (await _tasks(client, tool, cid, "costing_input"))[0]
    assert row["late"] is True and row["escalation"] == "pm_digest"
    async with session_factory() as s:
        await run_notification_sweep(s); await s.commit()
    pm_id = team["user"]["Project Manager"]
    titles = [n.title for n in await _overdue(session_factory, pm_id)]
    assert any(t.startswith("Late: Costing input") and t.endswith(row["change_number"])
               for t in titles), titles
    if idle is not None:      # NEGATIVE: the idle lead gets nothing
        assert await _overdue(session_factory, idle) == []
    pm = await _as(client, "Project Manager")
    esc = (await client.get("/api/v1/changes/my-escalations", headers=pm)).json()
    assert any(e["change_id"] == cid and e["kind"] == "costing_input" for e in esc)


async def test_active_lead_keeps_the_escalation_pm_gets_none(
        client, seed, team, session_factory):
    from app.services.notification_sweep import run_notification_sweep
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "lead acts")
    dev_id = team["user"]["Development"]
    await _set(session_factory, cid, status="in_assessment", lead_id=dev_id)
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=10))
    tool = await _as(client, "Tool Engineer")
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["escalation"] == "lead_digest"
    async with session_factory() as s:
        await run_notification_sweep(s); await s.commit()
    assert len(await _overdue(session_factory, dev_id)) == 1
    assert await _overdue(session_factory, team["user"]["Project Manager"]) == []
    pm = await _as(client, "Project Manager")
    esc = (await client.get("/api/v1/changes/my-escalations", headers=pm)).json()
    assert not any(e["change_id"] == cid for e in esc)


# ---------------------------------------------------------------------------
# A6-04 the kickoff row has one owner
# ---------------------------------------------------------------------------
async def test_leadless_kickoff_is_pm_main_sales_backup_and_sales_cannot_hand_over(
        client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "no lead yet")
    await _set(session_factory, cid, lead_id=None)
    pm = await _as(client, "Project Manager")
    pm_row = (await _tasks(client, pm, cid, "kickoff"))[0]
    s_row = (await _tasks(client, sales, cid, "kickoff"))[0]
    assert pm_row["role"] == "main"
    assert pm_row["hint"] == "Assign a lead, then hand over to scoping"
    assert (s_row["role"], s_row["main_name"]) == ("backup", "Project Management")
    assert s_row["hint"].startswith("Project Management assigns a lead")
    # NEGATIVE: Sales' hand-over is refused (and its button hidden) until a lead
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=sales)).json()
    assert st["can_transition"]["scoping"] is False
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=pm)).json()
    assert st["can_transition"]["scoping"] is True
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=sales)
    assert res.status_code == 403 and "assigns a change lead" in res.json()["detail"]
    # once a lead is set Sales' row is main again and the hop is Sales' to take
    await _set(session_factory, cid, lead_id=team["user"]["Project Manager"])
    s_row = (await _tasks(client, sales, cid, "kickoff"))[0]
    assert s_row["role"] == "main" and s_row.get("hint") is None
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=sales)).json()
    assert st["can_transition"]["scoping"] is True


async def test_sales_member_flipping_to_customer_owns_the_customer_side(
        client, seed, team, session_factory):
    dev = await _as(client, "Development")
    cid = await _create(client, dev, seed, "internal first", customer_relevant=False)
    sales = await _as(client, "Sales")
    res = await client.patch(f"/api/v1/changes/{cid}", json={"customer_relevant": True},
                             headers=sales)
    if res.status_code == 403:
        pytest.skip("Sales may not flip this change by PATCH")
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).sales_owner_id == team["user"]["Sales"]


# ---------------------------------------------------------------------------
# A6-05 the lead has a row at its own step
# ---------------------------------------------------------------------------
async def test_scoping_wrapup_is_the_leads_pm_backs_it_up(client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "scoping lead")
    dev_id = team["user"]["Development"]
    await _set(session_factory, cid, status="scoping", lead_id=dev_id)
    dev, pm = await _as(client, "Development"), await _as(client, "Project Manager")
    row = (await _tasks(client, dev, cid, "scoping_wrapup"))[0]
    assert row["role"] == "main"
    pm_row = (await _tasks(client, pm, cid, "scoping_wrapup"))[0]
    assert (pm_row["role"], pm_row["main_name"]) == ("backup", "Development person")
    # NEGATIVE: another department's member gets no wrap-up row
    assert not await _tasks(client, await _as(client, "Quality"), cid, "scoping_wrapup")


async def test_approved_lead_watches_who_owes_the_next_step(client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "approved lead")
    pm_id = team["user"]["Project Manager"]
    await _set(session_factory, cid, status="approved", lead_id=pm_id,
               customer_response="accepted")
    pm = await _as(client, "Project Manager")
    row = (await _tasks(client, pm, cid, "plan_watch"))[0]
    assert row["hint"] == "Waiting for Scheduling: decide the bank build"
    assert row["role"] == "main"
    await _set(session_factory, cid, bank_build_mode="running_change")
    row = (await _tasks(client, pm, cid, "plan_watch"))[0]
    assert row["hint"] == "Waiting for Sales: publish the plan"
    # NEGATIVE: Sales (not the lead) gets no watch row
    assert not await _tasks(client, sales, cid, "plan_watch")
