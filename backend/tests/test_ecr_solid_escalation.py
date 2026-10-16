"""ECR-solid one escalation rule + the overdue digest (spec §0, C20, C27/P6):

- the owner is reminded on the due date; at due + 1 working day the owner
  hears it is late and the change lead gets it ("Overdue" group, sweep);
- deadline alerts reach the Sales owner too;
- the daily digest goes to the configured managers only, once a day;
- entering implementation / validation tells the implementing departments.
Negative: nothing escalates before due + 1 wd; nobody else gets the digest;
switches off, nothing new is sent."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import (
    Department, UserDepartment, WfInstance, WfInstanceTask, WfTemplate,
)
from app.services import cm_switches, due_rules
from app.services.notification_sweep import run_notification_sweep

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _engineer_can_act(session_factory, seed):
    """A6-03: a late item escalates to a lead who can act; the seeded
    engineer leads here, so give it a PLM department (strategy B: no
    department = read-only, whose escalations go to Project Management)."""
    from tests.conftest import make_department_member
    await make_department_member(session_factory, seed["engineer_id"], "Lead Desk")


async def _change(s, seed, number, **kw):
    c = ChangeRequest(change_number=number, title="t", reason="r",
                      change_type="physical_part", project_id=seed["project_id"],
                      raised_by=seed["admin_id"], **kw)
    s.add(c)
    await s.flush()
    return c


async def _notes(s, **where):
    q = select(Notification)
    for k, v in where.items():
        q = q.where(getattr(Notification, k) == v)
    return (await s.execute(q)).scalars().all()


async def _dept(s, name="Process Engineer"):
    d = Department(name=name, flow_type="action", is_active=True)
    s.add(d)
    await s.flush()
    return d


async def test_lead_hears_only_at_due_plus_one_working_day(session_factory, seed):
    now = datetime.utcnow()
    async with session_factory() as s:
        d = await _dept(s)
        c = await _change(s, seed, "C-E-1", lead_id=seed["engineer_id"])
        fresh = ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                                 rasic_letter="R", due_date=now - timedelta(minutes=5))
        late = ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                                rasic_letter="R",
                                due_date=due_rules.sub_wd(now, 1) - timedelta(minutes=5))
        s.add_all([fresh, late]); await s.commit()
        await run_notification_sweep(s); await s.commit()
        keys = {n.subject_key for n in await _notes(s, user_id=seed["engineer_id"],
                                                    kind="overdue")}
        assert f"assessment:{late.id}:overdue:lead" in keys
        # negative: just past due is not late yet
        assert f"assessment:{fresh.id}:overdue:lead" not in keys


async def test_lead_overdue_group_waits_one_working_day(client, session_factory, seed):
    from tests.conftest import login
    now = datetime.utcnow()
    async with session_factory() as s:
        d = await _dept(s)
        c = await _change(s, seed, "C-E-2", lead_id=seed["admin_id"])
        s.add_all([
            ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                             rasic_letter="R", due_date=now - timedelta(minutes=5)),
            ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                             rasic_letter="R",
                             due_date=due_rules.sub_wd(now, 2))])
        await s.commit()
    res = await client.get("/api/v1/changes/my-escalations",
                           headers=await login(client, "admin@test.io"))
    assert res.status_code == 200, res.text
    rows = [r for r in res.json() if r["kind"] == "assessment"]
    assert len(rows) == 1


async def test_owner_reminded_on_the_due_date_not_before(session_factory, seed):
    now = datetime.utcnow()
    async with session_factory() as s:
        d = await _dept(s)
        tmpl = WfTemplate(name="e", version=1, is_active=True, created_by=1)
        s.add(tmpl); await s.flush()
        c = await _change(s, seed, "C-E-3")
        inst = WfInstance(template_id=tmpl.id, change_id=c.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        s.add(inst); await s.flush()
        end_of_today = now.replace(hour=23, minute=59, second=0, microsecond=0)
        today = WfInstanceTask(instance_id=inst.id, stage_order=1, department_id=d.id,
                               rasic_letter="R", status="active", is_actionable=True,
                               owner_id=seed["engineer_id"], due_date=end_of_today)
        later = WfInstanceTask(instance_id=inst.id, stage_order=1, department_id=d.id,
                               rasic_letter="R", status="active", is_actionable=True,
                               owner_id=seed["admin_id"],
                               due_date=end_of_today + timedelta(days=2))
        s.add_all([today, later]); await s.commit()
        await run_notification_sweep(s); await s.commit()
        assert [n.title for n in await _notes(s, user_id=seed["engineer_id"],
                                              kind="due_soon")] == ["Task due today"]
        assert not await _notes(s, user_id=seed["admin_id"], kind="due_soon")


async def test_deadline_alert_reaches_the_sales_owner(session_factory, seed):
    async with session_factory() as s:
        c = await _change(s, seed, "C-E-4", lead_id=seed["admin_id"],
                          sales_owner_id=seed["engineer_id"], customer_relevant=True,
                          required_by_date=datetime.utcnow() - timedelta(days=1))
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        for uid in (seed["admin_id"], seed["engineer_id"]):
            assert await _notes(s, user_id=uid, kind="deadline_overdue",
                                subject_key=f"chg:{c.id}:overdue")


async def test_daily_digest_to_the_configured_manager_once(
        session_factory, seed, monkeypatch):
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "admin")
    now = datetime.utcnow()
    async with session_factory() as s:
        d = await _dept(s)
        c = await _change(s, seed, "C-E-5", customer_relevant=True, status="quoting",
                          created_at=now - timedelta(days=10))
        s.add(ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                               rasic_letter="R", due_date=now - timedelta(days=9)))
        await _change(s, seed, "C-E-6")          # nothing late: not listed
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        got = await _notes(s, kind="overdue_digest")
        assert [n.user_id for n in got] == [seed["admin_id"]]   # never the engineer
        body = got[0].body
        assert body.startswith("C-E-5 (Quote creation)")
        assert "Process Engineer assessment" in body and "Sales: create the quote" in body
        assert "C-E-6" not in body
        # read it; a second sweep the same day sends no second digest
        got[0].is_read = True
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        assert len(await _notes(s, kind="overdue_digest")) == 1


async def test_switches_off_no_digest_and_no_stage_notice(
        session_factory, seed, monkeypatch):
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "admin")
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        c = await _change(s, seed, "C-E-7", customer_relevant=True, status="quoting",
                          created_at=datetime.utcnow() - timedelta(days=10))
        await s.commit()
        await run_notification_sweep(s); await s.commit()
        assert not await _notes(s, kind="overdue_digest")
        assert await ChangeService.notify_stage_entered(s, c, "in_validation") == 0


async def test_stage_entry_tells_the_implementing_departments(session_factory, seed):
    from app.models.change_cost import CostingPosition
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        d = await _dept(s)
        other = await _dept(s, "Quality")
        u = User(organization_id=seed["org_id"], username="pe", email="pe@test.io",
                 full_name="PE", hashed_password="x", role="engineer", is_active=True)
        q = User(organization_id=seed["org_id"], username="qa", email="qa@test.io",
                 full_name="QA", hashed_password="x", role="engineer", is_active=True)
        s.add_all([u, q]); await s.flush()
        s.add_all([UserDepartment(user_id=u.id, department_id=d.id),
                   UserDepartment(user_id=q.id, department_id=other.id)])
        c = await _change(s, seed, "C-E-8")
        # C23: a position with money is work (an empty one is not)
        s.add(CostingPosition(change_id=c.id, department_id=d.id, label="work",
                              est_cost=500.0, created_by=seed["admin_id"]))
        await s.commit()
        assert await ChangeService.notify_stage_entered(s, c, "in_validation") == 1
        await s.commit()
        assert await _notes(s, user_id=u.id, kind="stage_entered")
        assert not await _notes(s, user_id=q.id, kind="stage_entered")   # not involved
        # once per change and stage
        assert await ChangeService.notify_stage_entered(s, c, "in_validation") == 0
