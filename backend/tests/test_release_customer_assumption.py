"""P2-6 (Christoph 2026-11-02): an Assumed answer the customer still has to
confirm holds the release (HARD, no override); the refusal names the open
item and who confirms it. Our team's and a supplier's open assumptions only
warn (listed on the release state, never a blocker). Switch
ASSUMED_CUSTOMER_BLOCKS_RELEASE off: listed only, as before."""
from datetime import date, datetime

import pytest

from app.models.change import ChangeConcern, ChangeRequest
from app.services import cm_switches
from app.services.change_service import ChangeService
from tests.test_release_checklist import (  # noqa: F401  (fixture)
    _answer, _auth, _check, _owner, _state, rel_world,
)

pytestmark = pytest.mark.asyncio


async def _ready_but_assumed(client, rel_world, session_factory, monkeypatch, answer_from):
    async def ready(session, change):
        return {"ready_to_go": True, "items": []}
    monkeypatch.setattr(ChangeService, "implementation_progress", staticmethod(ready))
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    for c in (await _state(client, pm, cid))["checks"]:
        res = await _check(client, await _owner(client, c), cid, c["key"], "done",
                           **_answer(c["key"]))
        assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/changes/{cid}/lessons/complete",
                            json={"none_reason": "routine index change"}, headers=pm)
    assert res.status_code == 200
    async with session_factory() as s:
        q = ChangeConcern(
            change_id=cid, kind="needs_info", flag_type="question",
            note="Which rib height tolerance does the gauge need?",
            raised_by=rel_world["users"]["pm"], answer_from=answer_from,
            answered_at=datetime.utcnow(), answer_kind="assumed",
            assumed_value="0.1", assumed_unit="mm",
            confirm_by_id=rel_world["users"]["dev"], confirm_due=date(2026, 11, 5))
        s.add(q)
        await s.commit()
        return pm, cid, q.id


async def _release(client, pm, cid):
    return await client.post(f"/api/v1/changes/{cid}/transition",
                             json={"to_status": "released"}, headers=pm)


async def test_unconfirmed_customer_assumption_blocks_release(
        client, rel_world, session_factory, monkeypatch):
    pm, cid, qid = await _ready_but_assumed(client, rel_world, session_factory,
                                            monkeypatch, "customer")
    res = await _release(client, pm, cid)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "assumed customer answer not confirmed" in detail
    assert "0.1 mm: Which rib height tolerance" in detail
    assert "confirms: Rel dev, due 5 Nov 2026" in detail
    # HARD: no override is offered for it
    assert "x-deviation-required" not in {k.lower() for k in res.headers}
    st = await _state(client, pm, cid)
    assert st["can_release"] is False
    assert any("assumed customer answer" in b for b in st["blockers"])
    assert st["assumption_warnings"] == []
    # confirmed: the release goes through
    async with session_factory() as s:
        q = await s.get(ChangeConcern, qid)
        q.confirmed_at, q.confirmed_by, q.answer_kind = (
            datetime.utcnow(), rel_world["users"]["dev"], "confirmed")
        await s.commit()
    res = await _release(client, pm, cid)
    assert res.status_code == 200, res.text


async def test_supplier_assumption_only_warns(client, rel_world, session_factory, monkeypatch):
    pm, cid, _ = await _ready_but_assumed(client, rel_world, session_factory,
                                          monkeypatch, "supplier")
    st = await _state(client, pm, cid)
    assert st["blockers"] == [] and st["can_release"] is True
    assert len(st["assumption_warnings"]) == 1
    assert "confirms: Rel dev" in st["assumption_warnings"][0]
    res = await _release(client, pm, cid)
    assert res.status_code == 200, res.text


async def test_switch_off_lists_the_customer_assumption_only(
        client, rel_world, session_factory, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSUMED_CUSTOMER_BLOCKS_RELEASE", False)
    pm, cid, _ = await _ready_but_assumed(client, rel_world, session_factory,
                                          monkeypatch, "customer")
    st = await _state(client, pm, cid)
    assert st["blockers"] == [] and len(st["assumption_warnings"]) == 1
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert await ChangeService.customer_assumption_refusal(s, change) is None


async def test_why_blocked_names_the_customer_assumption(
        client, rel_world, session_factory, monkeypatch):
    pm, cid, _ = await _ready_but_assumed(client, rel_world, session_factory,
                                          monkeypatch, "customer")
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        got = await ChangeService.next_step_missing(s, change)
    items = got["items"] if isinstance(got, dict) else got
    [row] = [i for i in items if i["key"] == "customer_assumptions"]
    assert row["kind"] == "hard" and row["exits"] == ["confirm_assumption"]
    assert "Rel dev" in row["detail"]
