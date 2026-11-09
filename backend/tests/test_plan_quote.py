"""Real time vs the Sales buffer, bank builds as estimates (Christoph 2026-11-09)."""
import pytest

from app.utils.clock import business_today
from tests.test_plan_rules import (  # noqa: F401  (world is a fixture)
    _auth, _by_name, _get, _positions, _set, _url, world,
)

pytestmark = pytest.mark.asyncio


async def test_timing_splits_real_time_and_buffer(client, world, session_factory):
    await _positions(session_factory, world)
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    out = (await client.post(_url(cid, "/seed"), json={"plan": "quote"}, headers=sales)).json()
    tm = out["timing"]
    buf = _by_name(out)["Safety buffer"]
    assert tm["sales_buffer_task_id"] == buf["id"]
    assert tm["sales_buffer_days"] == buf["duration_days"]
    assert tm["total_days"] == tm["real_days"] + tm["sales_buffer_days"]
    # bank builds are estimates with the note
    bank = _by_name(out)["Bank build (idea)"]
    assert bank["estimate"] is True and "floats with the PO" in bank["estimate_note"]
    assert _by_name(out)["Gauge update"]["estimate"] is False


async def test_set_sales_buffer_in_weeks(client, world, session_factory):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    await client.post(_url(cid, "/seed"), json={"plan": "quote"}, headers=sales)
    res = await client.put(_url(cid, "/sales-buffer"), json={"plan": "quote", "weeks": 3},
                           headers=sales)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["timing"]["sales_buffer_days"] == 21
    assert out["timing"]["sales_buffer_weeks"] == 3.0
    assert _by_name(out)["Safety buffer"]["duration_days"] == 21
    # the SOP milestone follows the buffer
    assert _by_name(out)["Start of production (change)"]["start_date"] \
        == _by_name(out)["Safety buffer"]["end_date"]
    assert out["timing"]["total_weeks"] == round(out["timing"]["total_days"] / 7, 1)


async def test_sales_buffer_added_when_missing(client, world):
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    d = business_today().isoformat()
    await client.post(_url(cid, "/changes"), json={"plan": "quote", "changes": {
        "tasks_upsert": [{"id": "a", "name": "Work", "kind": "work", "start_date": d,
                          "duration_days": 14}]}}, headers=sales)
    res = await client.put(_url(cid, "/sales-buffer"), json={"plan": "quote", "weeks": 1},
                           headers=sales)
    assert res.status_code == 200, res.text
    t = _by_name(res.json())
    assert t["Sales buffer"]["kind"] == "buffer" and t["Sales buffer"]["duration_days"] == 7
    assert t["Sales buffer"]["start_date"] == t["Work"]["end_date"]
    tm = res.json()["timing"]
    assert (tm["real_days"], tm["sales_buffer_days"], tm["total_days"]) == (14, 7, 21)


async def test_sales_buffer_refused_after_acceptance(client, world, session_factory):
    from datetime import datetime
    sales = await _auth(client, "sales")
    cid = world["change_id"]
    await client.post(_url(cid, "/seed"), json={"plan": "quote"}, headers=sales)
    await _set(session_factory, cid, status="quoted", customer_response="accepted",
               customer_response_at=datetime.utcnow())
    res = await client.put(_url(cid, "/sales-buffer"), json={"plan": "quote", "weeks": 2},
                           headers=sales)
    assert res.status_code == 400
