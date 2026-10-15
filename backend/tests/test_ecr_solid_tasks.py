"""ECR-solid lane L3 (spec §0 My Tasks, due dates, ownership):

- C3: every move-forward step is a task: overrides to decide, sign-offs,
  the internal approval, open validation checks, the run team's "Ready:
  move it on"; decisions sit in "Needs you" on top, by due.
- C20: a row is due 2 wd after it became owed (1 wd urgent); the
  assessment by min(now + 7 d, deadline - 3 wd); late at due + 1 wd.
- The first person who edits a department's assessment owns it.
Negative cases: the proposer, other departments and the raiser get no row;
a second editor does not take the task over."""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import (
    ChangeAssessment, ChangeRequest, ChangeRoutingStandard, ChangeTransitionDeviation,
)
from app.models.entities import User
from app.models.workflow import (
    Department, UserDepartment, WfStage, WfStep, WfStepRasic, WfTemplate,
)
from app.services import cm_switches, due_rules
from tests.conftest import (
    approve_gates, lock_impact, login, record_proceed_meeting, satisfy_capture_gate,
)

pytestmark = pytest.mark.asyncio

NAMES = ("Sales", "Project Manager", "Development", "Quality", "Tool Engineer",
         "Process Engineer")


@pytest_asyncio.fixture
async def team(session_factory, seed):
    """One department per name, one member each (email <dept>@test.io), plus
    a second Tool Engineer (tool2@test.io)."""
    out = {"dept": {}, "user": {}}
    async with session_factory() as s:
        for i, n in enumerate(NAMES):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=(n == "Sales"),
                           can_start_internal_change=(n == "Development"))
            s.add(d); await s.flush(); out["dept"][n] = d.id
        for key, dept in [(n, n) for n in NAMES] + [("tool2", "Tool Engineer")]:
            slug = key.split()[0].lower()
            u = User(organization_id=seed["org_id"], username=slug,
                     email=f"{slug}@test.io", full_name=f"{key} person",
                     hashed_password=get_password_hash("x-secret-123"),
                     role="engineer", is_active=True, mfa_enabled=False)
            s.add(u); await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=out["dept"][dept]))
            out["user"][key] = u.id
        await s.commit()
    return out


async def _as(client, key):
    return await login(client, f"{key.split()[0].lower()}@test.io", admin=False)


async def _create(client, auth, seed, title="l3", **over):
    body = {"project_id": seed["project_id"], "title": title, "reason": "r",
            "change_type": "physical_part", "customer_relevant": True}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _set(session_factory, cid, **fields):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        for k, v in fields.items():
            setattr(c, k, v)
        await s.commit()


async def _tasks(client, auth, cid=None, kind=None):
    res = await client.get("/api/v1/changes/my-tasks", headers=auth)
    assert res.status_code == 200, res.text
    return [t for t in res.json()
            if (cid is None or t["change_id"] == cid) and (kind is None or t["kind"] == kind)]


# ---------------------------------------------------------------------------
# C20 on the rows
# ---------------------------------------------------------------------------
async def test_stage_row_is_due_two_working_days_after_it_became_owed(
        client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    dl = datetime.utcnow() + timedelta(days=20)
    cid = await _create(client, sales, seed)
    created = datetime.utcnow() - timedelta(hours=1)
    await _set(session_factory, cid, required_by_date=dl, created_at=created)
    row = (await _tasks(client, sales, cid, "kickoff"))[0]
    due = datetime.fromisoformat(row["due_date"])
    assert abs(due - due_rules.add_wd(created, 2)) < timedelta(seconds=2)
    # "due Thu (quote deadline Mon)": the deadline rides along
    assert row["deadline_kind"] == "quote"
    assert row["deadline_date"].startswith(dl.date().isoformat())
    assert row["overdue"] is False and row["late"] is False and row["urgent"] is False

    await _set(session_factory, cid, priority="critical")
    row = (await _tasks(client, sales, cid, "kickoff"))[0]
    assert abs(datetime.fromisoformat(row["due_date"]) - due_rules.add_wd(created, 1)) \
        < timedelta(seconds=2)
    assert row["urgent"] is True


async def test_late_one_working_day_after_due(client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, created_at=datetime.utcnow() - timedelta(days=10))
    row = (await _tasks(client, sales, cid, "kickoff"))[0]
    assert row["overdue"] is True and row["late"] is True


async def test_switch_off_rows_keep_the_change_deadline(
        client, seed, team, session_factory, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    row = (await _tasks(client, sales, cid, "kickoff"))[0]
    assert row["due_date"] is None and "deadline_date" not in row


# ---------------------------------------------------------------------------
# C3: Needs you
# ---------------------------------------------------------------------------
async def test_override_to_decide_is_in_needs_you_for_the_decider_only(
        client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    later = await _create(client, sales, seed, "plain")
    async with session_factory() as s:
        s.add(ChangeTransitionDeviation(
            change_id=cid, to_status="scoping", reason="customer waits",
            proposed_by=team["user"]["Sales"], status="pending"))
        await s.commit()
    pm = await _as(client, "Project Manager")
    rows = await _tasks(client, pm)
    mine = [t for t in rows if t["kind"] == "deviation_decision"]
    assert len(mine) == 1 and mine[0]["change_id"] == cid
    assert mine[0]["needs_you"] is True
    assert mine[0]["kind_label"].startswith("Decide override")
    assert rows[0]["kind"] == "deviation_decision"   # "Needs you" on top
    # negative: the proposer never decides their own; Development may not
    assert not await _tasks(client, sales, cid, "deviation_decision")
    assert not await _tasks(client, await _as(client, "Development"), cid,
                            "deviation_decision")
    assert later  # a second change keeps the list honest


async def test_sign_offs_after_acceptance_each_side_once(
        client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="quoted", customer_response="accepted",
               customer_response_at=datetime.utcnow())
    pm, quality = await _as(client, "Project Manager"), await _as(client, "Quality")
    pm_rows = await _tasks(client, pm, cid, "sign_off")
    assert [r["side"] for r in pm_rows] == ["pm"] and pm_rows[0]["needs_you"]
    assert [r["side"] for r in await _tasks(client, quality, cid, "sign_off")] == ["quality"]
    # negative: nobody else; a signed side is gone
    assert not await _tasks(client, await _as(client, "Development"), cid, "sign_off")
    await _set(session_factory, cid, pm_signed_by=team["user"]["Project Manager"],
               pm_signed_at=datetime.utcnow())
    assert not await _tasks(client, pm, cid, "sign_off")
    # not before the customer said yes
    await _set(session_factory, cid, customer_response="pending")
    assert not await _tasks(client, quality, cid, "sign_off")


async def test_internal_approval_waits_on_the_approver_never_the_raiser(
        client, seed, team, session_factory):
    dev = await _as(client, "Development")
    cid = await _create(client, dev, seed, customer_relevant=False)
    await _set(session_factory, cid, status="costing")
    pm = await _as(client, "Project Manager")
    rows = await _tasks(client, pm, cid, "internal_approval")
    assert len(rows) == 1 and rows[0]["needs_you"] is True
    # negative: raised by the PM member, the PM member gets no approval row
    own = await _create(client, dev, seed, "pm raised", customer_relevant=False)
    await _set(session_factory, own, status="costing",
               raised_by=team["user"]["Project Manager"])
    assert not await _tasks(client, pm, own, "internal_approval")
    assert not await _tasks(client, dev, cid, "internal_approval")


async def test_run_team_gets_ready_to_move_on(client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="released",
               lead_id=team["user"]["Project Manager"])
    pm = await _as(client, "Project Manager")
    rows = await _tasks(client, pm, cid, "advance")
    assert len(rows) == 1 and rows[0]["to_status"] == "closed"
    assert rows[0]["needs_you"] is False
    # negative: not for Sales, and not while something holds the hop
    assert not await _tasks(client, sales, cid, "advance")
    await _set(session_factory, cid, price_open=True)
    assert not await _tasks(client, pm, cid, "advance")


async def test_cockpit_lists_the_same_steps(client, seed, team, session_factory):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed)
    await _set(session_factory, cid, status="quoted", customer_response="accepted")
    async with session_factory() as s:
        for _ in range(2):
            s.add(ChangeTransitionDeviation(
                change_id=cid, to_status="approved", reason="r",
                proposed_by=team["user"]["Sales"], status="pending"))
        await s.commit()
    pm = await _as(client, "Project Manager")
    res = await client.get(f"/api/v1/changes/{cid}/my-actions", headers=pm)
    assert res.status_code == 200, res.text
    actions = res.json()["actions"]
    kinds = [a["kind"] for a in actions]
    assert kinds.count("deviation_decision") == 2    # two overrides, two rows
    assert kinds.count("sign_off") == 1


# ---------------------------------------------------------------------------
# C20 assessment rule + first editor owns
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def routed(client, seed, team, session_factory, part):
    """A tooling change routed to Tool Engineer + Process Engineer (R), its
    quote deadline 6 working days out."""
    async with session_factory() as s:
        t = WfTemplate(name="ECR-l3", description="x", version=1, is_active=True,
                       created_by=1)
        s.add(t); await s.flush()
        stage = WfStage(template_id=t.id, stage_order=1, name="S1")
        s.add(stage); await s.flush()
        step = WfStep(stage_id=stage.id, step_name="S1", position_in_stage=1)
        s.add(step); await s.flush()
        for n in ("Tool Engineer", "Process Engineer"):
            s.add(WfStepRasic(step_id=step.id, department_id=team["dept"][n],
                              rasic_letter="R"))
        s.add(ChangeRoutingStandard(change_type="tooling", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
    admin = await login(client, "admin@test.io")
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "routed", "change_type": "tooling",
        "lead_id": seed["admin_id"]}, headers=admin)
    cid = res.json()["id"]
    res = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                            json={"part_id": part["part_id"], "is_lead": True},
                            headers=admin)
    assert res.status_code == 200, res.text
    await approve_gates(client, admin, cid)
    await satisfy_capture_gate(client, admin, cid)
    assert (await client.post(f"/api/v1/changes/{cid}/transition",
                              json={"to_status": "scoping"}, headers=admin)).status_code == 200
    deadline = due_rules.add_wd(datetime.utcnow(), 6)
    res = await client.patch(f"/api/v1/changes/{cid}",
                             json={"required_by_date": deadline.isoformat(),
                                   "required_by_reason": "customer moved it"},
                             headers=admin)
    assert res.status_code == 200, res.text
    await record_proceed_meeting(session_factory, cid, None)
    await lock_impact(session_factory, cid)
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_assessment"}, headers=admin)
    assert res.status_code == 200, res.text
    return {"id": cid, "deadline": deadline}


async def _row(session_factory, cid, dept_id):
    async with session_factory() as s:
        return (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == dept_id))).scalar_one()


async def test_assessment_due_runs_against_the_quote_deadline(
        session_factory, team, routed):
    a = await _row(session_factory, routed["id"], team["dept"]["Tool Engineer"])
    want = due_rules.sub_wd(routed["deadline"], 3)
    assert abs(a.effective_due_date - want) < timedelta(minutes=5)
    assert a.effective_due_date < datetime.utcnow() + timedelta(days=7)


async def test_first_editor_owns_the_assessment(client, session_factory, team, routed):
    cid = routed["id"]
    a = await _row(session_factory, cid, team["dept"]["Tool Engineer"])
    assert a.effective_owner_id is None
    url = f"/api/v1/changes/{cid}/assessments/{a.id}/draft"
    res = await client.put(url, json={"draft": {"notes": "x"}},
                           headers=await _as(client, "Tool Engineer"))
    assert res.status_code == 200, res.text
    a = await _row(session_factory, cid, team["dept"]["Tool Engineer"])
    assert a.effective_owner_id == team["user"]["Tool Engineer"]
    # negative: the second editor works on it but does not take it over
    res = await client.put(url, json={"draft": {"notes": "y"}},
                           headers=await _as(client, "tool2"))
    assert res.status_code == 200, res.text
    a = await _row(session_factory, cid, team["dept"]["Tool Engineer"])
    assert a.effective_owner_id == team["user"]["Tool Engineer"]
    # negative: another department may not edit it at all
    res = await client.put(url, json={"draft": {"notes": "z"}},
                           headers=await _as(client, "Process Engineer"))
    assert res.status_code == 403
    # the list names the owner
    rows = await _tasks(client, await _as(client, "tool2"), cid, "assessment")
    assert rows and rows[0]["owner_name"] == "Tool Engineer person"


async def test_admin_edit_does_not_own(client, session_factory, team, routed):
    """An admin's edit is no department person working on it."""
    cid = routed["id"]
    a = await _row(session_factory, cid, team["dept"]["Process Engineer"])
    res = await client.put(f"/api/v1/changes/{cid}/assessments/{a.id}/draft",
                           json={"draft": {"notes": "admin"}},
                           headers=await login(client, "admin@test.io"))
    assert res.status_code == 200, res.text
    a = await _row(session_factory, cid, team["dept"]["Process Engineer"])
    assert a.effective_owner_id is None
