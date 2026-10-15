"""ECR-solid C23 (spec §8-9, switch ASSESSMENT_V2): the progress cadence asks
only who does work, and stops asking while they wait or once they are done.

- Zero lines and empty positions are no work: such a department owes no
  report. A department whose assessment said "impact yes" does work.
- Waiting on a supplier (until its expected date) pauses the cadence.
- "Our part done" ends it; a later report without it starts it again.
"""
import json
from datetime import date, datetime, timedelta

import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine, CostingPosition
from app.services import cm_switches
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio
IMPACTED = json.dumps({"impacts": [{"key": "x", "answer": "yes", "impacted": True}]})


async def _member(client, session_factory, seed, key, dept):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"pc-{key}",
                 email=f"pc-{key}@test.io", full_name=f"PC {key}",
                 hashed_password=get_password_hash("pc-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    did = await make_department_member(session_factory, uid, dept)
    return did, await login(client, f"pc-{key}@test.io")


@pytest.fixture
async def impl(client, session_factory, seed):
    tool, te = await _member(client, session_factory, seed, "te", "Tool Engineer")
    proc, pe = await _member(client, session_factory, seed, "pe", "Process Engineer")
    pack, pk = await _member(client, session_factory, seed, "pk", "Packaging Engineer")
    async with session_factory() as s:
        change = ChangeRequest(
            change_number="C-PC-1", title="cadence", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"],
            status="in_implementation")
        s.add(change)
        await s.flush()
        rows = {}
        for did, details in ((tool, None), (proc, IMPACTED), (pack, None)):
            a = ChangeAssessment(change_id=change.id, department_id=did, stage_order=1,
                                 verdict="feasible", details=details)
            s.add(a)
            await s.flush()
            rows[did] = a.id
        # Tool Engineer priced real work; Packaging only a seeded zero line
        s.add(CostingPosition(change_id=change.id, department_id=tool,
                              label="Insert re-cut", kind="external",
                              pricing="estimate", est_cost=900.0,
                              created_by=seed["admin_id"]))
        s.add(AssessmentCostLine(assessment_id=rows[pack], plant_id=1,
                                 cost_kind="one_time", demand_hours=0))
        await s.commit()
        cid = change.id
    return {"cid": cid, "tool": tool, "proc": proc, "pack": pack,
            "te": te, "pe": pe, "pk": pk}


async def _state(client, auth, impl):
    res = await client.get(f"/api/v1/changes/{impl['cid']}/implementation/state",
                           headers=auth)
    assert res.status_code == 200, res.text
    return {d["department_id"]: d for d in res.json()["departments"]}


async def test_only_who_does_work_owes_a_report(client, admin_auth, impl):
    st = await _state(client, admin_auth, impl)
    assert set(st) == {impl["tool"], impl["proc"]}     # zero line: no work
    assert st[impl["proc"]]["owes_report"] is True     # impact yes, unpriced
    # negative: a zero-line department may not report on work it does not do
    res = await client.post(f"/api/v1/changes/{impl['cid']}/implementation/reports",
                            json={"department_id": impl["pack"], "note": "nothing"},
                            headers=impl["pk"])
    assert res.status_code in (400, 403)


async def test_our_part_done_ends_the_cadence(client, admin_auth, impl):
    url = f"/api/v1/changes/{impl['cid']}/implementation/reports"
    # negative: done and at risk at once
    res = await client.post(url, json={"department_id": impl["tool"], "note": "x",
                                       "part_done": True, "at_risk": True},
                            headers=impl["te"])
    assert res.status_code == 400
    res = await client.post(url, json={"department_id": impl["tool"],
                                       "note": "Insert re-cut and back", "part_done": True},
                            headers=impl["te"])
    assert res.status_code in (200, 201), res.text
    st = await _state(client, admin_auth, impl)
    assert st[impl["tool"]]["cadence"] == "done"
    assert st[impl["tool"]]["owes_report"] is False


async def test_a_supplier_wait_pauses_the_cadence(client, admin_auth, impl):
    res = await client.post(f"/api/v1/changes/{impl['cid']}/supplier-waits", json={
        "department_id": impl["tool"], "vendor_name": "FZ",
        "asked_on": (date.today() - timedelta(days=3)).isoformat(),
        "expected_by": (date.today() + timedelta(days=20)).isoformat()},
        headers=impl["te"])
    assert res.status_code == 200, res.text
    assert res.json()[0]["phase"] == "implementation"
    st = await _state(client, admin_auth, impl)
    assert st[impl["tool"]]["cadence"] == "waiting"
    assert st[impl["tool"]]["waiting_on"] == "FZ"
    assert st[impl["tool"]]["owes_report"] is False
    assert st[impl["proc"]]["owes_report"] is True      # nobody else is paused


async def test_switch_off_keeps_the_old_cadence(client, admin_auth, impl, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    st = await _state(client, admin_auth, impl)
    assert set(st) == {impl["tool"], impl["pack"]}      # any line counted, as before
