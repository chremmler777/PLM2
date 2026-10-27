"""A5-03 (R37, RELEASE_V2): a department the detailed plan waits on with no
real member here (Scheduling in prod) is confirmed by the lead, no lead:
Project Management; its task goes to them and the row says so."""
import pytest

from app.models.change import ChangeRequest
from app.models.entities import User
from tests.test_change_plan import _approved_with_detailed, _auth, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _feedback(client, cid, auth):
    return (await client.get(f"/api/v1/changes/{cid}/plan/feedback", headers=auth)).json()


async def _plan_tasks(client, auth, cid):
    return [t for t in (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
            if t["change_id"] == cid and t["kind"] == "plan_feedback"]


async def test_a5_03_negative_lead_or_pm_confirms_a_memberless_department(
        client, world, session_factory):
    cid, sales = await _approved_with_detailed(client, world, session_factory)
    async with session_factory() as s:
        (await s.get(User, world["users"]["sched"])).is_active = False
        await s.commit()
    sched, tool = world["depts"]["Logistics"], world["depts"]["Tool Engineer"]
    pm = await _auth(client, "pm")
    fb = await _feedback(client, cid, pm)
    row = next(r for r in fb["required"] if r["department_id"] == sched)
    assert row["no_member"] is True and row["can_answer"] is True
    assert row["hint"] == "Logistics has no member here: Project Management coordinates"
    # no lead: PM's task, worded
    tasks = await _plan_tasks(client, pm, cid)
    assert [t["department_id"] for t in tasks] == [sched]
    assert "no member here" in tasks[0]["hint"]
    # NEGATIVE: PM does not answer for a staffed department, nor does a
    # member of another one for Scheduling
    res = await client.post(f"/api/v1/changes/{cid}/plan/feedback", headers=pm,
                            json={"department_id": tool, "verdict": "confirmed"})
    assert res.status_code == 403, res.text
    res = await client.post(f"/api/v1/changes/{cid}/plan/feedback",
                            headers=await _auth(client, "tool"),
                            json={"department_id": sched, "verdict": "confirmed"})
    assert res.status_code == 403, res.text
    # with a lead: the lead's task, named
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).lead_id = world["users"]["apqp"]
        await s.commit()
    apqp = await _auth(client, "apqp")
    assert await _plan_tasks(client, pm, cid) == []
    tasks = await _plan_tasks(client, apqp, cid)
    assert [t["department_id"] for t in tasks] == [sched]
    assert tasks[0]["hint"].startswith("Logistics has no member here: Plan apqp coordinates")
    res = await client.post(f"/api/v1/changes/{cid}/plan/feedback", headers=apqp,
                            json={"department_id": sched, "verdict": "confirmed"})
    assert res.status_code == 200, res.text
    assert next(r for r in res.json()["required"]
                if r["department_id"] == sched)["verdict"] == "confirmed"
