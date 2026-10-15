"""ECR-solid lane L6 (flow spec rev 6 §6-§7a, switch COMMERCIAL_V2).

§6 Send: the offer states the index letter each part goes out on and warns
when the customer already sent a newer one; Send lists the unconfirmed
Assumed answers and the estimates, and an open high risk the offer does not
states (a hidden one) needs a reason (pick + sentence) to go out.
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.change import ChangeChangelog, ChangeConcern, ChangeImpactedItem
from app.services import cm_switches
from tests.test_offers import (  # noqa: F401  (offer_world is a fixture)
    _auth, _create, _url, offer_world,
)

pytestmark = pytest.mark.asyncio


async def _no_timing(client, sales, cid, oid):
    res = await client.patch(_url(cid, f"/{oid}"),
                             json={"data": {"timing": {"include": False}}},
                             headers=sales)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
async def risky(session_factory, offer_world):
    """The offer world plus an open severity-3 risk and an unconfirmed
    Assumed answer (a scoping question answered internally)."""
    async with session_factory() as s:
        risk = ChangeConcern(
            change_id=offer_world["change_id"], kind="risk", note="weld line on A-side",
            risk_type="fill_issue", severity=3,
            department_id=offer_world["depts"]["Tool Engineer"],
            raised_by=offer_world["users"]["tool"])
        assumed = ChangeConcern(
            change_id=offer_world["change_id"], kind="needs_info", flag_type="question",
            note="Annual volume for the new variant?", answer_from="customer",
            raised_by=offer_world["users"]["sales"], answer_kind="assumed",
            assumed_value="40000", assumed_unit="pcs/yr",
            assumed_risk="tool sized one cavity too small",
            confirm_by_id=offer_world["users"]["sales"], confirm_due=date(2026, 11, 2))
        s.add_all([risk, assumed])
        await s.commit()
        return {**offer_world, "risk_id": risk.id, "assumed_id": assumed.id}


async def test_send_lists_assumed_answers_estimates_and_high_risks(client, risky):
    cid = risky["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    listed = o["send_list"]
    assert [a["concern_id"] for a in listed["assumed"]] == [risky["assumed_id"]]
    a = listed["assumed"][0]
    assert (a["value"], a["risk"], a["confirm_due"], a["confirm_by_name"]) == (
        "40000 pcs/yr", "tool sized one cavity too small", "2026-11-02", "Offer sales")
    assert listed["estimates"] == ["Insert rework (Hasco)"]
    assert [r["concern_id"] for r in listed["high_risks"]] == [risky["risk_id"]]


async def test_hidden_high_risk_needs_a_reason_to_go_out(client, risky, session_factory):
    cid = risky["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    await _no_timing(client, sales, cid, o["id"])
    # NEGATIVE: no reason, then a reason that says nothing
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 400
    assert "high risk not on this offer" in res.json()["detail"]
    res = await client.post(_url(cid, f"/{o['id']}/send"),
                            json={"risk_reason_code": "customer_aware",
                                  "risk_reason": "ok"}, headers=sales)
    assert res.status_code == 400
    res = await client.post(_url(cid, f"/{o['id']}/send"),
                            json={"risk_reason_code": "customer_aware",
                                  "risk_reason": "Customer accepted the weld line in DFM 2026-10-02"},
                            headers=sales)
    assert res.status_code == 200, res.text
    sent = res.json()
    # the sent version keeps what it listed and why it went out
    assert sent["send_list"]["risk_reason_code"] == "customer_aware"
    assert len(sent["send_list"]["assumed"]) == 1
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
    assert "offer_sent_with_risk" in rows


async def test_a_stated_high_risk_goes_out_without_a_reason(client, risky):
    cid = risky["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    risks = o["data"]["risks"]
    for r in risks:
        if r["concern_id"] == risky["risk_id"]:
            r.update(show=True)      # stated, no surcharge: the customer reads it
    res = await client.patch(_url(cid, f"/{o['id']}"),
                             json={"data": {"risks": risks, "timing": {"include": False}}},
                             headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["send_list"]["high_risks"] == []
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 200, res.text


async def test_switch_off_sends_without_the_list(client, risky, monkeypatch):
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    cid = risky["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    assert o["send_list"] is None
    await _no_timing(client, sales, cid, o["id"])
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 200, res.text


async def test_offer_states_index_and_warns_on_an_older_one(
        client, offer_world, session_factory, seed):
    from app.models.part import Part, PartRevision
    cid = offer_world["change_id"]
    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="886.197",
                    name="Bezel", part_type="internal_mfg", item_category="article",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        rev_c = PartRevision(part_id=part.id, revision_name="3", phase="official",
                             customer_index="C", source="customer",
                             created_by=seed["admin_id"])
        s.add(rev_c)
        await s.flush()
        s.add(ChangeImpactedItem(change_id=cid, part_id=part.id,
                                 resulting_revision_id=rev_c.id,
                                 created_by=offer_world["users"]["sales"]))
        await s.commit()
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    assert {"number": "886.197", "index": "C", "newer": None} in o["indexes"]
    assert "index_older" not in {w["code"] for w in o["warnings"]}
    async with session_factory() as s:
        s.add(PartRevision(part_id=part.id, revision_name="4", phase="official",
                           customer_index="D", source="customer",
                           customer_received_at=date(2026, 10, 12),
                           created_by=seed["admin_id"]))
        await s.commit()
    res = await client.get(_url(cid), headers=sales)
    draft = res.json()[0]
    row = next(i for i in draft["indexes"] if i["number"] == "886.197")
    assert row["newer"]["index"] == "D"
    warn = next(w for w in draft["warnings"] if w["code"] == "index_older")
    assert "886.197 C" in warn["message"] and "sent D" in warn["message"]
    # a warning, never a refusal: Send still goes out, and freezes C
    await _no_timing(client, sales, cid, o["id"])
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 200, res.text
    assert {"number": "886.197", "index": "C", "newer": None} in res.json()["indexes"]
