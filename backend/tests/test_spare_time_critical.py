"""Christoph 2026-11-09: "It needs to be identified if spare parts are time
critical or not, that changes the sales timing. Have 30 days as time leader;
if not needed it needs to jump to 15 days for the tool eng favourite."

A spare part line says time_critical yes/no. Yes (or not answered yet): its
delivery counts for the lead time. No: it is left out of every lead-time
roll-up (summation, plan). Finalize asks for the answer."""
import pytest

from app.models.change_cost import CostingPosition
from tests.test_ecr_solid_no_cost_and_waits import _u, ec  # noqa: F401 (fixture)

pytestmark = pytest.mark.asyncio


async def _line(client, ec, **body):
    res = await client.post(_u(ec, "/costing/positions"), json={
        "department_id": ec["shop"], "kind": "external", "pricing": "quote", **body},
        headers=ec["dale"])
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _offer(client, ec, pid, vendor, days):
    res = await client.post(_u(ec, f"/costing/positions/{pid}/offers"), json={
        "vendor_name": vendor, "cost": 500.0, "shipping_cost": 0,
        "lead_time_days": days, "lead_time_unit": "calendar_days"}, headers=ec["dale"])
    assert res.status_code in (200, 201), res.text


async def _change_31(client, ec):
    """Change 31's shape: tool change favourite Hitech 15 d, spare part Hasco 30 d."""
    tool = await _line(client, ec, label="Toolchange", quantity=1, quantity_unit="job",
                       notes="From the assessment: External modification (supplier)")
    await _offer(client, ec, tool, "Hitech", 15)
    spare = await _line(client, ec, label="Ejector pins", quantity=20, quantity_unit="pcs",
                        notes="From the assessment: Spare part required")
    await _offer(client, ec, spare, "Hasco", 30)
    return tool, spare


async def _lead(client, ec, admin_auth):
    summ = (await client.get(_u(ec, "/summation"), headers=admin_auth)).json()
    by = {d["department_id"]: d["lead_time_days"] for d in summ["lead_time_by_department"]}
    return summ["max_lead_time_days"], by.get(ec["shop"])


async def test_only_a_spare_part_that_is_not_time_critical_is_left_out():
    spare = CostingPosition(kind="external", label="Spare part: pins", notes=None)
    assert spare.is_spare_part and spare.counts_for_lead_time      # unanswered counts
    spare.time_critical = True
    assert spare.counts_for_lead_time
    spare.time_critical = False
    assert not spare.counts_for_lead_time
    tool = CostingPosition(kind="external", label="Toolchange",
                           notes="From the assessment: External modification",
                           time_critical=False)
    assert not tool.is_spare_part and tool.counts_for_lead_time
    own = CostingPosition(kind="own_time", label="spare part handling", time_critical=False)
    assert not own.is_spare_part and own.counts_for_lead_time


async def test_spare_part_time_critical_sets_the_lead_time(client, ec, admin_auth):
    _, spare = await _change_31(client, ec)
    rows = {p["id"]: p for p in (await client.get(
        _u(ec, "/costing/positions"), headers=ec["dale"])).json()}
    assert rows[spare]["is_spare_part"] is True
    assert rows[spare]["time_critical"] is None
    assert rows[spare]["counts_for_lead_time"] is True
    # not answered yet: the spare part counts (the safe side)
    assert await _lead(client, ec, admin_auth) == (30, 30)

    res = await client.put(_u(ec, f"/costing/positions/{spare}"),
                           json={"time_critical": True}, headers=ec["dale"])
    assert res.status_code == 200, res.text
    assert res.json()["time_critical"] is True
    assert await _lead(client, ec, admin_auth) == (30, 30)    # spare part is the time leader

    res = await client.put(_u(ec, f"/costing/positions/{spare}"),
                           json={"time_critical": False}, headers=ec["dale"])
    assert res.status_code == 200, res.text
    assert res.json()["time_critical"] is False
    assert res.json()["counts_for_lead_time"] is False
    # not needed for the change: the tool change favourite (Hitech 15 d) leads
    assert await _lead(client, ec, admin_auth) == (15, 15)


async def test_finalize_asks_if_the_spare_part_is_time_critical(client, ec):
    # the spare part alone (a catalogue buy needs no quote file / no.)
    spare = await _line(client, ec, label="Ejector pins", quantity=20, quantity_unit="pcs",
                        notes="From the assessment: Spare part required")
    await _offer(client, ec, spare, "Hasco", 30)
    chk = _u(ec, f"/costing/departments/{ec['shop']}/finalize-check")
    check = (await client.get(chk, headers=ec["dale"])).json()
    items = [i for i in check["items"] if i["tag"] == "time_critical_missing"]
    assert [i["text"] for i in items] == ["Ejector pins: say if the spare part is time critical"]
    assert spare in check["position_ids"]
    res = await client.post(_u(ec, f"/costing/departments/{ec['shop']}/finalize"),
                            headers=ec["dale"])
    assert res.status_code == 400, res.text
    assert "time critical" in res.json()["detail"]

    res = await client.put(_u(ec, f"/costing/positions/{spare}"),
                           json={"time_critical": False}, headers=ec["dale"])
    assert res.status_code == 200, res.text
    check = (await client.get(chk, headers=ec["dale"])).json()
    assert not [i for i in check["items"] if i["tag"] == "time_critical_missing"]
