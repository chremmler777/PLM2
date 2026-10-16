"""ECR-solid close-out, area 4 (commercial / offer / sign-offs).

A4-01 the price-drop baseline: the last accepted total, else the highest
version sent since (an unanswered lower version in between never resets
it); supplements against the highest supplement since the last accepted
version; a lower piece price effect is a drop too.
"""
import pytest
from sqlalchemy import select

from tests.test_offers import (  # noqa: F401  (offer_world is a fixture)
    _auth, _create, _url, offer_world,
)
from tests.test_ecr_solid_commercial import (  # noqa: F401  (fixtures)
    _YES, _answer, _no_timing, _raise_position, _supplement, _v2_with_discount,
    approved, quoted,
)

pytestmark = pytest.mark.asyncio


async def _send(client, cid, sales, oid, note):
    res = await client.post(_url(cid, f"/{oid}/send"), json={"change_note": note},
                            headers=sales)
    assert res.status_code == 200, res.text
    return res.json()


async def test_an_unanswered_lower_version_never_resets_the_baseline(client, quoted):
    """v1 1000, v2 900 (no answer), v3 950: accepting v3 is 50 below v1."""
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    await _v2_with_discount(client, cid, sales, 10)
    v3 = await _v2_with_discount(client, cid, sales, 5)
    assert v3["version"] == 3 and v3["totals"]["total_one_time"] == 950
    assert v3["price_drop"]["prev_version"] == 1     # the dialog asks, too
    # NEGATIVE: no reason, no automatic approval
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400, res.text
    assert "v3 at 950.00 is below v1 at 1000.00" in res.json()["detail"]


async def test_an_equal_step_down_after_a_lower_version_still_asks(client, quoted):
    """The audit case: v1, v2 lower (no answer), v3 at v2's total."""
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    v2 = await _v2_with_discount(client, cid, sales, 10)
    res = await client.post(_url(cid), headers=sales)
    v3 = res.json()
    res = await client.patch(_url(cid, f"/{v3['id']}"), json={"data": {
        "factors": v2["data"]["factors"],
        "free_fields": [{"label": "Delivery FCA Spartanburg", "value": "", "amount": 0}]}},
        headers=sales)
    assert res.status_code == 200, res.text
    await _send(client, cid, sales, v3["id"], "Delivery terms")
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400 and "below v1" in res.json()["detail"]


async def _with_piece_price(client, cid, sales, per_piece):
    res = await client.post(_url(cid), headers=sales)
    assert res.status_code == 201, res.text
    o = res.json()
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {"piece_price": {
        "enabled": True, "annual_volume": 10000,
        "rows": [{"label": "Insert", "delta_per_piece": per_piece}]}}}, headers=sales)
    assert res.status_code == 200, res.text
    return await _send(client, cid, sales, o["id"], f"Piece price {per_piece}")


async def test_a_lower_piece_price_effect_needs_the_ok(client, quoted, session_factory):
    from app.models.change import ChangeTransitionDeviation
    cid = quoted["change_id"]
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    await _with_piece_price(client, cid, sales, 0.10)       # 1000 / yr
    v3 = await _with_piece_price(client, cid, sales, 0.05)  # 500 / yr, same total
    assert v3["totals"]["total_one_time"] == 1000
    # NEGATIVE: the one-time total is the same, the recurring side is lower
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400, res.text
    assert "piece price effect to 500.00/yr (v2: 1000.00/yr)" in res.json()["detail"]
    res = await _answer(client, cid, sales, {
        **_YES, "price_drop_code": "volume",
        "price_drop_note": "Volume doubled per the buyer mail of 14 Oct"})
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        dev = (await s.execute(select(ChangeTransitionDeviation).where(
            ChangeTransitionDeviation.change_id == cid,
            ChangeTransitionDeviation.guard_key == "price_drop"))).scalar_one()
    assert dev.status == "pending"


async def test_a_higher_piece_price_needs_no_reason(client, quoted):
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    await _with_piece_price(client, cid, sales, 0.05)
    await _with_piece_price(client, cid, sales, 0.10)
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 200, res.text


async def test_a_supplement_stepped_down_through_a_middle_one_asks(
        client, approved, session_factory):
    """S1 +500, S2 +100 (no answer), S3 +300: S3 is below S1."""
    cid, sales = approved["change_id"], approved["sales"]
    for amount, note in ((1500, "Rework higher"), (1100, "Rework lower"),
                         (1300, "Rework middle")):
        await _raise_position(session_factory, approved, amount)
        s = await _supplement(client, cid, sales)
        sent = await _send(client, cid, sales, s["id"], note)
    assert sent["totals"]["total_one_time"] == 300
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400, res.text
    assert f"below v{sent['version'] - 2}" in res.json()["detail"]
