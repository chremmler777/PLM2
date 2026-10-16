"""ECR-solid C7 / §10 (RELEASE_V2): release checklist rows are answered by
their department; PM, the lead or an admin only for a department nobody in
the change's organization belongs to (no dead end). The customer's approval
is a reference to a document, not a tick. The ERP row reads the routing
time from the measured cycle time."""
import pytest

from app.models.change_validation import ValidationCheck
from app.services import cm_switches
from tests.test_release_checklist import _auth, _check, _state, rel_world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_negative_pm_does_not_tick_an_owned_row(client, rel_world, admin_auth):
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    for auth in (pm, admin_auth):
        res = await _check(client, auth, cid, "index_updated", "done")
        assert res.status_code == 403, res.text
    st = await _state(client, pm, cid)
    rows = {c["key"]: c for c in st["checks"]}
    assert rows["index_updated"]["can_answer"] is False
    # a department nobody belongs to (Packaging Engineer is not seeded,
    # Scheduling has no member): PM answers, so nothing is stuck
    assert rows["packaging_updated"]["can_answer"] is True
    assert rows["erp_updated"]["can_answer"] is True
    res = await _check(client, pm, cid, "erp_updated", "done")
    assert res.status_code == 200, res.text
    dev = await _auth(client, "dev")
    res = await _check(client, dev, cid, "index_updated", "done")
    assert res.status_code == 200, res.text
    assert {c["key"]: c for c in res.json()["checks"]}["index_updated"]["status"] == "done"


async def test_customer_approval_needs_a_reference(client, rel_world):
    cid = rel_world["change_id"]
    apqp = await _auth(client, "apqp")
    for note in (None, "ok", "done"):
        res = await _check(client, apqp, cid, "customer_approval", "done", note)
        assert res.status_code == 400, res.text
        assert "customer's approval" in res.json()["detail"]
    res = await _check(client, apqp, cid, "customer_approval", "done",
                       "PSW 886.197-D signed 2026-10-12")
    assert res.status_code == 200, res.text
    row = {c["key"]: c for c in res.json()["checks"]}["customer_approval"]
    assert row["needs_ref"] is True and row["note"].startswith("PSW 886.197-D")


async def test_erp_row_reads_the_measured_routing_time(client, rel_world, session_factory):
    cid = rel_world["change_id"]
    async with session_factory() as s:
        s.add(ValidationCheck(change_id=cid, check_key="cycle_time", status="passed",
                              department_id=rel_world["depts"]["Tool Engineer"],
                              value=41.1))
        await s.commit()
    st = await _state(client, await _auth(client, "pm"), cid)
    erp = {c["key"]: c for c in st["checks"]}["erp_updated"]
    assert erp["hint"] == "Routing time from validation: 41.1 s"


async def test_switch_off_pm_ticks_any_row_and_no_reference(client, rel_world, monkeypatch):
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    assert (await _check(client, pm, cid, "index_updated", "done")).status_code == 200
    assert (await _check(client, pm, cid, "customer_approval", "done")).status_code == 200
