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


# ---------------------------------------------------------------------------
# §7 the customer's answer (C4, C12) and approval on the last of three
# ---------------------------------------------------------------------------
_DUE = "2026-12-18T00:00:00"
_YES = {"response": "accepted", "release_due_date": _DUE, "ref": "PO 4500123456",
        "po_match": "yes", "confirm_total": True}


@pytest.fixture
async def quoted(client, session_factory, offer_world):
    """offer_world with v1 sent (quoted) and a Quality member."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        q = Department(name="Quality", flow_type="action", is_active=True)
        s.add(q)
        await s.flush()
        u = User(organization_id=(await s.get(User, offer_world["users"]["sales"])).organization_id,
                 username="off-quality", email="off-quality@test.io",
                 full_name="Offer quality", role="engineer",
                 hashed_password=get_password_hash("role-secret-1"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=q.id))
        await s.commit()
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    await _no_timing(client, sales, cid, o["id"])
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 200, res.text
    return {**offer_world, "offer_id": o["id"], "quality_id": u.id}


async def _answer(client, cid, auth, body):
    return await client.post(f"/api/v1/changes/{cid}/customer-response",
                             json=body, headers=auth)


async def test_accept_needs_evidence_match_and_the_total(client, quoted, session_factory):
    from app.models.change_offer import ChangeOffer
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    # NEGATIVE: no evidence, empty evidence, no match answer, a "no" without
    # what differs, the total not confirmed
    for body, words in (
            ({**_YES, "ref": None}, "evidence"),
            ({**_YES, "ref": "ok"}, "says nothing"),
            ({**_YES, "po_match": None}, "PO matches offer v1"),
            ({**_YES, "po_match": "no"}, "name the parts"),
            ({**_YES, "confirm_total": False}, "Confirm the customer says yes to v1")):
        res = await _answer(client, cid, sales, body)
        assert res.status_code == 400, body
        assert words in res.json()["detail"], res.json()["detail"]
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 200, res.text
    assert res.json()["customer_response"] == "accepted"
    async with session_factory() as s:
        o = await s.get(ChangeOffer, quoted["offer_id"])
        assert o.status == "accepted"
        assert o.accept_evidence["ref"] == "PO 4500123456"
        assert (o.accept_evidence["po_match"], o.accept_evidence["version"]) == ("yes", 1)
        assert o.answered_by == quoted["users"]["sales"]


async def test_accept_with_a_filed_mail_never_another_changes(client, quoted, session_factory, seed):
    from app.models.change import ChangeAttachment, ChangeRequest
    cid = quoted["change_id"]
    async with session_factory() as s:
        other = ChangeRequest(change_number="C-O-2", title="other", reason="x",
                              change_type="physical_part", project_id=seed["project_id"],
                              raised_by=quoted["users"]["sales"], customer_relevant=True,
                              status="quoted")
        s.add(other)
        await s.flush()
        mine = ChangeAttachment(change_id=cid, kind="customer_email", filename="PO yes.msg",
                                stored_path="x", content_type="application/vnd.ms-outlook",
                                size_bytes=1, sha256="0" * 64,
                                uploaded_by=quoted["users"]["sales"])
        theirs = ChangeAttachment(change_id=other.id, kind="customer_email",
                                  filename="other.msg", stored_path="y",
                                  content_type="application/vnd.ms-outlook",
                                  size_bytes=1, sha256="1" * 64,
                                  uploaded_by=quoted["users"]["sales"])
        s.add_all([mine, theirs])
        await s.commit()
    sales = await _auth(client, "sales")
    res = await _answer(client, cid, sales, {**_YES, "ref": None, "attachment_id": theirs.id})
    assert res.status_code == 400 and "filed on this change" in res.json()["detail"]
    res = await _answer(client, cid, sales, {**_YES, "ref": None, "attachment_id": mine.id})
    assert res.status_code == 200, res.text


async def test_declined_rejects_with_the_customers_ref_and_letter_task(client, quoted):
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    res = await _answer(client, cid, sales, {"response": "declined"})
    assert res.status_code == 400            # NEGATIVE: no reference
    res = await _answer(client, cid, sales, {"response": "declined",
                                             "ref": "Mail 2026-10-14 Mr Klein: too expensive"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "rejected"
    assert body["rejection_reason"].startswith("Customer declined offer v1")
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    rows = tasks if isinstance(tasks, list) else tasks.get("tasks", [])
    assert any(t["kind"] == "send_rejection" and t["change_id"] == cid for t in rows)


async def test_still_talking_keeps_the_task_due_on_the_next_contact(client, quoted):
    from app.utils.clock import business_today
    from datetime import timedelta
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    past = (business_today() - timedelta(days=2)).isoformat()
    res = await _answer(client, cid, sales, {"response": "negotiating", "next_contact": past})
    assert res.status_code == 400            # NEGATIVE: a contact in the past
    nxt = (business_today() + timedelta(days=9)).isoformat()
    res = await _answer(client, cid, sales, {"response": "negotiating", "next_contact": nxt})
    assert res.status_code == 200, res.text
    assert res.json()["customer_next_contact"] == nxt
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    rows = tasks if isinstance(tasks, list) else tasks.get("tasks", [])
    row = next(t for t in rows if t["kind"] == "customer_response" and t["change_id"] == cid)
    assert str(row["due_date"]).startswith(nxt)


async def test_approval_follows_the_last_of_acceptance_and_both_signatures(client, quoted):
    cid = quoted["change_id"]
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    from tests.conftest import login, ENGINEER_PASSWORD
    q = await login(client, "off-quality@test.io", ENGINEER_PASSWORD)
    res = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=pm)
    assert res.status_code == 200, res.text
    res = await _answer(client, cid, sales, _YES)
    # NEGATIVE: Quality has not signed: no approval yet
    assert res.json()["status"] == "quoted"
    res = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "quality"}, headers=q)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"


async def test_switch_off_keeps_the_old_answer(client, quoted, monkeypatch):
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    res = await _answer(client, cid, sales, {"response": "accepted", "release_due_date": _DUE})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "quoted"


# ---------------------------------------------------------------------------
# §7 [R4] price diff: a lower accepted total needs a reason and an OK
# ---------------------------------------------------------------------------
async def _v2_with_discount(client, cid, sales, pct):
    res = await client.post(_url(cid), headers=sales)
    assert res.status_code == 201, res.text
    v2 = res.json()
    factors = v2["data"]["factors"]
    for f in factors:
        if f["key"] == "discount":
            f.update(enabled=True, value=pct)
    res = await client.patch(_url(cid, f"/{v2['id']}"), json={"data": {"factors": factors}},
                             headers=sales)
    assert res.status_code == 200, res.text
    res = await client.post(_url(cid, f"/{v2['id']}/send"),
                            json={"change_note": f"Discount {pct} %"}, headers=sales)
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_lower_total_needs_a_reason_and_the_pm_ok(client, quoted, session_factory):
    from app.models.change import ChangeTransitionDeviation
    from tests.conftest import login, ENGINEER_PASSWORD
    cid = quoted["change_id"]
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    q = await login(client, "off-quality@test.io", ENGINEER_PASSWORD)
    await _v2_with_discount(client, cid, sales, 10)
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400            # NEGATIVE: no reason for the drop
    assert "below v1" in res.json()["detail"]
    res = await _answer(client, cid, sales, {**_YES, "price_drop_code": "competitor",
                                             "price_drop_note": "ok"})
    assert res.status_code == 400            # NEGATIVE: a reason that says nothing
    res = await _answer(client, cid, sales, {
        **_YES, "price_drop_code": "competitor",
        "price_drop_note": "Competitor offered 8 % less, mail of 13 Oct"})
    assert res.status_code == 200, res.text
    for role, who in (("pm", pm), ("quality", q)):
        r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": role}, headers=who)
        assert r.status_code == 200, r.text
    # NEGATIVE: accepted and signed, but the drop waits for its OK
    assert r.json()["status"] == "quoted"
    async with session_factory() as s:
        dev = (await s.execute(select(ChangeTransitionDeviation).where(
            ChangeTransitionDeviation.change_id == cid,
            ChangeTransitionDeviation.guard_key == "price_drop"))).scalar_one()
    assert (dev.status, dev.reason_code) == ("pending", "competitor")
    # NEGATIVE: the asker never decides it
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev.id}/decide",
                          json={"decision": "approved"}, headers=sales)
    assert r.status_code == 400 and "4-eyes" in r.json()["detail"]
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev.id}/decide",
                          json={"decision": "approved"}, headers=pm)
    assert r.status_code == 200, r.text
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    assert ch["status"] == "approved"


async def test_a_higher_total_needs_no_reason(client, quoted):
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    await _v2_with_discount(client, cid, sales, -5)   # a negative discount: +5 %
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 200, res.text
