"""Planning rules and plan reset / delete (Christoph 2026-11-09).

  a. a tool change starts only after its mold bank build is finished;
  b. a trial starts only after the tool and gauge changes are finished;
  c. an assembly trial starts only after the line change is finished;
  d. a line change starts only after its assembly bank build is finished.
Refused with a code (400) when a write creates a new violation between
committed blocks, listed in the plan's issues; ideas only warn. The reset
deletes the plan and seeds it again, the delete leaves it empty; both are
logged and refused once the customer accepted the quote plan or timing was
validated.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeChangelog, ChangeRequest
from app.models.change_cost import CostingOffer, CostingPosition
from app.models.change_plan import ChangePlanTask
from app.models.workflow import Department, UserDepartment
from app.services import plan_rules as pr
from app.utils.clock import business_today
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- pure rules
def _t(i, name, kind, start, dur, *, idea=False, lane=None):
    t = ChangePlanTask(id=i, name=name, kind=kind, start_date=start,
                       duration_days=dur, is_idea=idea, lane=lane)
    t.parent_id = None
    return t


class _L:
    def __init__(self, a, b):
        self.from_task_id, self.to_task_id = a, b


D0 = date(2027, 1, 4)


def _roles(tasks):
    return {t.id: pr.classify(t.kind, t.name, t.lane, None, None) for t in tasks}


def test_classify():
    c = pr.classify
    assert c("downtime", "Insert rework - Hasco", "Tool Engineer", "Tool Engineer", None) == pr.TOOL_CHANGE
    assert c("supplier", "Insert", "Tool Engineer", None, "tool_change") == pr.TOOL_CHANGE
    assert c("downtime", "Spare insert", "Tool Engineer", None, "spare_part") is None
    assert c("supplier", "Gauge update", "APQP", "APQP", None) == pr.GAUGE_CHANGE
    assert c("supplier", "Fixture", "Quality", None, "gauge_change") == pr.GAUGE_CHANGE
    assert c("supplier", "Nest rework", "Manufacturing Engineer", None, None) == pr.LINE_CHANGE
    assert c("work", "Line change", None, None, None) == pr.LINE_CHANGE
    assert c("bank_build", "Bank build (idea)", "Logistics", None, None) == pr.MOLD_BANK
    assert c("bank_build", "Assembly bank build", "Logistics", None, None) == pr.ASSEMBLY_BANK
    assert c("sampling", "Sampling / trial", "Tool Engineer", None, None) == pr.TRIAL
    assert c("sampling", "Assembly trial", None, None, None) == pr.ASSEMBLY_TRIAL
    assert c("work", "Tool Engineer engineering", "Tool Engineer", None, None) is None
    assert c("validation", "Measurement and validation", "APQP", None, None) is None


def test_rule_a_tool_change_after_mold_bank_build():
    bank = _t(1, "Bank build", "bank_build", D0, 10)
    tool = _t(2, "Insert rework", "downtime", D0 + timedelta(days=5), 20)
    tasks = [bank, tool]
    found = pr.check(tasks, [], _roles(tasks))
    assert [v["code"] for v in found] == ["tool_change_during_bank_build"]
    assert "may only start after the mold bank build" in found[0]["message"]
    tool.start_date = D0 + timedelta(days=10)          # = bank end: allowed
    assert pr.check(tasks, [], _roles(tasks)) == []


def test_rule_a_idea_bank_only_warns():
    bank = _t(1, "Bank build (idea)", "bank_build", D0, 10, idea=True)
    tool = _t(2, "Insert rework", "downtime", D0, 20)
    found = pr.check([bank, tool], [], _roles([bank, tool]))
    assert found and found[0]["idea"] is True
    assert pr.violation_keys(found) == set()
    assert pr.as_issues(found)["errors"] == []


def test_rule_a_linked_bank_applies_to_its_own_tool_change_only():
    bank = _t(1, "Bank build", "bank_build", D0, 10)
    mine = _t(2, "Tool A rework", "downtime", D0 + timedelta(days=10), 5)
    other = _t(3, "Tool B rework", "downtime", D0, 5)
    tasks = [bank, mine, other]
    assert pr.check(tasks, [_L(1, 2)], _roles(tasks)) == []
    assert len(pr.check(tasks, [], _roles(tasks))) == 1   # unlinked: all


def test_rule_b_trial_after_tool_and_gauge():
    tool = _t(1, "Insert rework", "downtime", D0, 10)
    gauge = _t(2, "Gauge update", "supplier", D0, 14)
    trial = _t(3, "Sampling / trial", "sampling", D0 + timedelta(days=10), 5)
    tasks = [tool, gauge, trial]
    found = pr.check(tasks, [], _roles(tasks))
    assert [v["code"] for v in found] == ["trial_before_change_done"]
    assert found[0]["other_id"] == 2                     # the later one named
    trial.start_date = D0 + timedelta(days=14)
    assert pr.check(tasks, [], _roles(tasks)) == []


def test_rule_c_and_d_assembly():
    abank = _t(1, "Assembly bank build", "bank_build", D0, 10)
    line = _t(2, "Nest rework", "downtime", D0 + timedelta(days=3), 10,
              lane="Manufacturing Engineer")
    atrial = _t(3, "Assembly trial", "sampling", D0 + timedelta(days=12), 3)
    tasks = [abank, line, atrial]
    codes = sorted(v["code"] for v in pr.check(tasks, [], _roles(tasks)))
    assert codes == ["assembly_trial_before_line_done",
                     "line_change_during_bank_build"]
    line.start_date = D0 + timedelta(days=10)
    atrial.start_date = D0 + timedelta(days=20)
    assert pr.check(tasks, [], _roles(tasks)) == []


def test_mold_bank_does_not_bind_line_change():
    bank = _t(1, "Bank build", "bank_build", D0, 10)
    line = _t(2, "Line change", "downtime", D0, 5, lane="Manufacturing Engineer")
    assert pr.check([bank, line], [], _roles([bank, line])) == []


# ---------------------------------------------------------------- API world
@pytest.fixture
async def world(session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        depts = {}
        for name in ("Sales", "Project Manager", "Logistics", "Tool Engineer",
                     "APQP", "Manufacturing Engineer"):
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for key, dept in (("sales", "Sales"), ("pm", "Project Manager"),
                          ("tool", "Tool Engineer")):
            u = User(organization_id=seed["org_id"], username=f"rule-{key}",
                     email=f"rule-{key}@test.io", full_name=f"Rule {key}",
                     role="engineer",
                     hashed_password=get_password_hash("role-secret-1"),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[dept]))
            users[key] = u.id
        change = ChangeRequest(
            change_number="C-R-1", title="rules", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=users["sales"], customer_relevant=True, status="costing",
            impact_confirmed_at=datetime.utcnow(), impact_confirmed_by=users["pm"])
        s.add(change)
        await s.commit()
        return {"change_id": change.id, "depts": depts, "users": users}


async def _auth(client, key):
    return await login(client, f"rule-{key}@test.io", ENGINEER_PASSWORD)


async def _set(session_factory, cid, **fields):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        for k, v in fields.items():
            setattr(c, k, v)
        await s.commit()


async def _positions(session_factory, world, *, line=False):
    cid, depts, uid = world["change_id"], world["depts"], world["users"]["tool"]
    async with session_factory() as s:
        tool = CostingPosition(change_id=cid, department_id=depts["Tool Engineer"],
                               label="Insert rework", kind="external", tag="tool_change",
                               pricing="quote", created_by=uid)
        s.add(tool)
        await s.flush()
        s.add(CostingOffer(position_id=tool.id, vendor_name="Hasco", cost=5000,
                           lead_time_days=20, lead_time_unit="calendar_days",
                           favorite=True, created_by=uid))
        s.add(CostingPosition(change_id=cid, department_id=depts["APQP"],
                              label="Gauge update", kind="external", tag="gauge_change",
                              pricing="estimate", est_cost=800, lead_time_days=10,
                              lead_time_unit="calendar_days", created_by=uid))
        if line:
            s.add(CostingPosition(
                change_id=cid, department_id=depts["Manufacturing Engineer"],
                label="Nest rework", kind="external", tag="fixture_change",
                pricing="estimate", est_cost=900, lead_time_days=7,
                lead_time_unit="calendar_days", created_by=uid))
        await s.commit()


def _url(cid, tail=""):
    return f"/api/v1/changes/{cid}/plan{tail}"


async def _get(client, auth, cid, plan="quote"):
    res = await client.get(_url(cid) + f"?plan={plan}", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


def _by_name(out):
    return {t["name"]: t for t in out["tasks"]}


def _day(iso, n):
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


# ---------------------------------------------------------------- reset / delete
async def test_reset_reseeds_and_logs(client, world, session_factory):
    await _positions(session_factory, world)
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    assert (await client.post(_url(cid, "/seed"), json={"plan": "quote"},
                              headers=sales)).status_code == 200
    seeded = await _get(client, sales, cid)
    assert seeded["reset_blocked_reason"] is None
    extra = await client.post(_url(cid, "/tasks"), json={
        "plan": "quote", "name": "My own block", "start_date": business_today().isoformat(),
        "duration_days": 2}, headers=sales)
    assert extra.status_code == 200, extra.text
    res = await client.post(_url(cid, "/reset"), json={"plan": "quote"}, headers=sales)
    assert res.status_code == 200, res.text
    names = {t["name"] for t in res.json()["tasks"]}
    assert "My own block" not in names
    assert names == {t["name"] for t in seeded["tasks"]}
    async with session_factory() as s:
        acts = [r.action for r in (await s.execute(
            select(ChangeChangelog).where(ChangeChangelog.change_id == cid)
            .order_by(ChangeChangelog.id))).scalars()]
    assert "plan_reset" in acts and acts[-1] == "plan_seeded"


async def test_delete_leaves_plan_empty_and_seedable(client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    await client.post(_url(cid, "/seed"), json={"plan": "quote"}, headers=sales)
    res = await client.delete(_url(cid) + "?plan=quote", headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["tasks"] == []
    again = await client.post(_url(cid, "/seed"), json={"plan": "quote"}, headers=sales)
    assert again.status_code == 200 and again.json()["tasks"]
    async with session_factory() as s:
        acts = [r.action for r in (await s.execute(
            select(ChangeChangelog).where(ChangeChangelog.change_id == cid))).scalars()]
    assert "plan_deleted" in acts


async def test_reset_refused_after_customer_accepted(client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    await client.post(_url(cid, "/seed"), json={"plan": "quote"}, headers=sales)
    await _set(session_factory, cid, status="quoted", customer_response="accepted",
               customer_response_at=datetime.utcnow())
    out = await _get(client, sales, cid)
    assert "accepted the offer" in out["reset_blocked_reason"]
    for res in (await client.post(_url(cid, "/reset"), json={"plan": "quote"}, headers=sales),
                await client.delete(_url(cid) + "?plan=quote", headers=sales)):
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "plan_locked"
        assert "accepted the offer" in res.json()["detail"]["message"]
    assert len((await _get(client, sales, cid))["tasks"]) == len(out["tasks"])


async def test_reset_refused_once_timing_validated(client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    await _set(session_factory, cid, status="approved")
    assert (await client.post(_url(cid, "/seed"), json={"plan": "detailed"},
                              headers=sales)).status_code == 200
    await _set(session_factory, cid, timing_validated_at=datetime.utcnow())
    res = await client.post(_url(cid, "/reset"), json={"plan": "detailed"}, headers=sales)
    assert res.status_code == 400
    assert "timing was validated" in res.json()["detail"]["message"]


async def test_reset_only_for_plan_editors(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    await client.post(_url(cid, "/seed"), json={"plan": "quote"}, headers=sales)
    tool = await _auth(client, "tool")
    res = await client.post(_url(cid, "/reset"), json={"plan": "quote"}, headers=tool)
    assert res.status_code == 403
    assert (await _get(client, tool, cid))["reset_blocked_reason"].startswith("Only")


# ---------------------------------------------------------------- rules over the API
async def test_seed_respects_rules_and_roles(client, world, session_factory):
    await _positions(session_factory, world, line=True)
    await _set(session_factory, world["change_id"], bank_build_mode="planned_scrap")
    sales = await _auth(client, "sales")
    res = await client.post(_url(world["change_id"], "/seed"), json={"plan": "quote"},
                            headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    roles = {t["name"]: t["rule_role"] for t in out["tasks"]}
    assert roles["Insert rework - Hasco"] == "tool_change"
    assert roles["Gauge update"] == "gauge_change"
    assert roles["Nest rework"] == "line_change"
    assert roles["Bank build"] == "mold_bank_build"
    assert roles["Assembly bank build"] == "assembly_bank_build"
    assert roles["Sampling / trial"] == "trial"
    t = _by_name(out)
    assert t["Bank build"]["end_date"] <= t["Insert rework - Hasco"]["start_date"]
    assert t["Assembly bank build"]["end_date"] <= t["Nest rework"]["start_date"]
    codes = {i["code"] for i in out["validation"]["errors"]}
    assert not codes & {"tool_change_during_bank_build", "line_change_during_bank_build",
                        "trial_before_change_done", "assembly_trial_before_line_done"}


async def test_move_tool_change_into_bank_build_refused(client, world, session_factory):
    await _positions(session_factory, world)
    await _set(session_factory, world["change_id"], bank_build_mode="planned_scrap")
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    out = (await client.post(_url(cid, "/seed"), json={"plan": "quote"}, headers=sales)).json()
    t = _by_name(out)
    tool, bank = t["Insert rework - Hasco"], t["Bank build"]
    res = await client.patch(_url(cid, f"/tasks/{tool['id']}"), json={
        "start_date": _day(bank["start_date"], 2)}, headers=sales)
    assert res.status_code == 400, res.text
    assert res.json()["detail"]["code"] == "tool_change_during_bank_build"
    assert "mold bank build" in res.json()["detail"]["message"]
    # nothing kept
    assert _by_name(await _get(client, sales, cid))["Insert rework - Hasco"]["start_date"] \
        == tool["start_date"]


async def _manual(client, auth, cid, blocks):
    """Unlinked blocks in one ChangeSet (no links: the rules alone hold them)."""
    res = await client.post(_url(cid, "/changes"), json={"plan": "quote", "changes": {
        "tasks_upsert": [{"id": f"tmp-{i}", **b} for i, b in enumerate(blocks)]}},
        headers=auth)
    return res


async def test_trial_before_gauge_done_refused(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    d = business_today().isoformat()
    res = await _manual(client, sales, cid, [
        {"name": "Gauge update", "kind": "supplier", "lane": "APQP", "start_date": d,
         "duration_days": 10},
        {"name": "Sampling / trial", "kind": "sampling", "start_date": _day(d, 5),
         "duration_days": 3}])
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "trial_before_change_done"
    ok = await _manual(client, sales, cid, [
        {"name": "Gauge update", "kind": "supplier", "lane": "APQP", "start_date": d,
         "duration_days": 10},
        {"name": "Sampling / trial", "kind": "sampling", "start_date": _day(d, 10),
         "duration_days": 3}])
    assert ok.status_code == 200, ok.text
    trial = _by_name(ok.json())["Sampling / trial"]
    moved = await client.patch(_url(cid, "/tasks"), json={"plan": "quote", "updates": [
        {"id": trial["id"], "start_date": _day(d, 9)}]}, headers=sales)
    assert moved.status_code == 400
    assert "gauge" in moved.json()["detail"]["message"]


async def test_assembly_trial_and_line_change_rules(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    d = business_today().isoformat()
    ok = await _manual(client, sales, cid, [
        {"name": "Assembly bank build", "kind": "bank_build", "lane": "Logistics",
         "start_date": d, "duration_days": 5},
        {"name": "Nest rework", "kind": "downtime", "lane": "Manufacturing Engineer",
         "start_date": _day(d, 5), "duration_days": 5},
        {"name": "Assembly trial", "kind": "sampling", "start_date": _day(d, 10),
         "duration_days": 2}])
    assert ok.status_code == 200, ok.text
    t = _by_name(ok.json())
    res = await client.patch(_url(cid, f"/tasks/{t['Assembly trial']['id']}"),
                             json={"start_date": _day(d, 8)}, headers=sales)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "assembly_trial_before_line_done"
    res = await client.patch(_url(cid, f"/tasks/{t['Nest rework']['id']}"),
                             json={"start_date": _day(d, 3)}, headers=sales)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "line_change_during_bank_build"


async def test_old_violation_listed_but_does_not_block_other_edits(
        client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    d = business_today()
    async with session_factory() as s:
        for name, kind, start, dur in (("Bank build", "bank_build", d, 10),
                                       ("Insert rework", "downtime", d, 5),
                                       ("Docs", "work", d, 2)):
            s.add(ChangePlanTask(change_id=cid, plan="quote", name=name, kind=kind,
                                 start_date=start, duration_days=dur, predecessors=[],
                                 created_by=world["users"]["sales"]))
        await s.commit()
    out = await _get(client, sales, cid)
    assert any(i["code"] == "tool_change_during_bank_build"
               for i in out["validation"]["errors"])
    docs = _by_name(out)["Docs"]
    res = await client.patch(_url(cid, f"/tasks/{docs['id']}"),
                             json={"duration_days": 3}, headers=sales)
    assert res.status_code == 200, res.text


async def test_idea_bank_build_only_warns(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    d = business_today().isoformat()
    res = await _manual(client, sales, cid, [
        {"name": "Bank build (idea)", "kind": "bank_build", "is_idea": True,
         "start_date": d, "duration_days": 10},
        {"name": "Insert rework", "kind": "downtime", "start_date": d, "duration_days": 5}])
    assert res.status_code == 200, res.text
    v = res.json()["validation"]
    assert any(w["code"] == "tool_change_during_bank_build" for w in v["warnings"])
    assert not any(e["code"] == "tool_change_during_bank_build" for e in v["errors"])
