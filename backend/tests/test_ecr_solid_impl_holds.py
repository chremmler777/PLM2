"""ECR-solid §8-9 (lane L7, switch RELEASE_V2): approved -> implementation.

- The detailed plan is confirmed by the departments with work to plan
  (impact yes or hours / cost on the change), Scheduling, and Sales only
  on a customer change; an R department with no impact and no cost is not
  waited on.
- 'Newer index pending' is a SOFT hold at the start of implementation and
  at release: an index of an impacted part waiting for triage (or an open
  recheck / the lead's question) is settled first, or overridden.
"""
from datetime import datetime

import pytest
from sqlalchemy import update

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import CostingPosition
from app.services import cm_switches
from app.services.change_plan_service import ChangePlanService
from tests.test_ecr_solid_intake import _change_carrying, _intake, _receive  # noqa: F401
from tests.test_revision_intake import _auth, world  # noqa: F401

pytestmark = pytest.mark.asyncio
API = "/api/v1"


async def _required(session_factory, cid):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        await s.refresh(c, ["assessments"])
        return set(await ChangePlanService.required_department_ids(s, c))


async def test_plan_confirmers_are_the_departments_with_work(session_factory, world):
    d = world["depts"]
    cid = await _change_carrying(session_factory, world, "approved",
                                 submitted=("Tool Engineer", "Packaging Engineer"))
    async with session_factory() as s:
        s.add(CostingPosition(change_id=cid, department_id=d["Tool Engineer"],
                              label="Insert", kind="external", pricing="estimate",
                              est_cost=1200.0, created_by=world["seed"]["admin_id"]))
        await s.commit()
    req = await _required(session_factory, cid)
    # Packaging is R but has no impact and no cost: not waited on (NEGATIVE)
    assert d["Tool Engineer"] in req and d["Packaging Engineer"] not in req
    assert d["Sales"] in req
    # an internal change has no customer to tell: no Sales
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(customer_relevant=False))
        await s.commit()
    assert d["Sales"] not in await _required(session_factory, cid)


async def test_switch_off_keeps_every_r_department(session_factory, world, monkeypatch):
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    d = world["depts"]
    cid = await _change_carrying(session_factory, world, "approved",
                                 submitted=("Tool Engineer", "Packaging Engineer"))
    req = await _required(session_factory, cid)
    assert {d["Tool Engineer"], d["Packaging Engineer"], d["Sales"]} <= req


async def test_newer_index_waiting_for_triage_holds_implementation(
        client, session_factory, world, monkeypatch):
    cid = await _change_carrying(session_factory, world, "approved")
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid).values(
            timing_validated_at=datetime.utcnow(), impact_confirmed_at=datetime.utcnow(),
            bank_build_mode="none"))
        await s.commit()
    r = await _receive(client, world["part_id"])
    assert r.status_code in (200, 201), r.text
    admin = await _auth(client, "admin")
    res = await client.post(f"{API}/changes/{cid}/transition",
                            json={"to_status": "in_implementation"}, headers=admin)
    assert res.status_code == 400, res.text
    assert "Newer index pending: Index" in res.json()["detail"]
    assert "waits for triage" in res.json()["detail"]
    assert res.headers.get("X-Deviation-Required") == "in_implementation"   # SOFT
    ch = (await client.get(f"{API}/changes/{cid}", headers=admin)).json()
    row = next(i for i in ch["next_step"]["items"] if i["key"] == "index_pending")
    assert row["kind"] == "soft" and row["rule"] == "index_pending"
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    res = await client.post(f"{API}/changes/{cid}/transition",
                            json={"to_status": "in_implementation"}, headers=admin)
    assert "Newer index pending" not in res.text


async def test_no_department_with_work_falls_back_to_the_r_departments(session_factory, world):
    """NEGATIVE (no dead end): a change nobody priced and nobody said 'impact
    yes' on still has someone to confirm its plan: the R/A departments."""
    d = world["depts"]
    cid = await _change_carrying(session_factory, world, "approved",
                                 submitted=("Tool Engineer",))
    req = await _required(session_factory, cid)
    assert {d["Tool Engineer"], d["Packaging Engineer"]} <= req
