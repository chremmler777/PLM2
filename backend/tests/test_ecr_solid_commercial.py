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


# ---------------------------------------------------------------------------
# C14: signatures bound to the offer; a new version withdraws them (PM
# always, Quality on a technical change, a part index included)
# ---------------------------------------------------------------------------
async def _part_on_change(session_factory, seed, cid, index="C"):
    from app.models.part import Part, PartRevision
    async with session_factory() as s:
        part = Part(project_id=seed["project_id"], part_number="886.197", name="Bezel",
                    part_type="internal_mfg", item_category="article",
                    created_by=seed["admin_id"])
        s.add(part)
        await s.flush()
        rev = PartRevision(part_id=part.id, revision_name="3", phase="official",
                           customer_index=index, source="customer",
                           created_by=seed["admin_id"])
        s.add(rev)
        await s.flush()
        item = ChangeImpactedItem(change_id=cid, part_id=part.id, resulting_revision_id=rev.id,
                                  created_by=seed["admin_id"])
        s.add(item)
        await s.commit()
        return part.id, item.id


async def _signed_v1(client, session_factory, seed, offer_world, with_part=False):
    """quoted-like world built by hand: Quality member, optional part, v1
    sent, both signed on v1 before the customer answers."""
    from tests.conftest import login, ENGINEER_PASSWORD
    cid = offer_world["change_id"]
    part = await _part_on_change(session_factory, seed, cid) if with_part else None
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    o = await _create(client, sales, cid)
    await _no_timing(client, sales, cid, o["id"])
    assert (await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)).status_code == 200
    q = await login(client, "off-quality@test.io", ENGINEER_PASSWORD)
    for role, who in (("pm", pm), ("quality", q)):
        r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": role}, headers=who)
        assert r.status_code == 200, r.text
    return cid, sales, pm, q, part


@pytest.fixture
async def quality_member(session_factory, offer_world):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        q = Department(name="Quality", flow_type="action", is_active=True)
        s.add(q)
        await s.flush()
        u = User(organization_id=(await s.get(User, offer_world["users"]["sales"])).organization_id,
                 username="off-quality", email="off-quality@test.io", full_name="Offer quality",
                 role="engineer", hashed_password=get_password_hash("role-secret-1"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=q.id))
        await s.commit()
        return u.id


async def test_a_price_only_version_withdraws_the_pm_signature_only(
        client, session_factory, seed, offer_world, quality_member):
    from app.models.notification import Notification
    cid, sales, pm, q, _ = await _signed_v1(client, session_factory, seed, offer_world)
    await _v2_with_discount(client, cid, sales, -5)
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "signoff_withdrawn"))).scalars().all()
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == offer_world["users"]["pm"]))).scalars().all()
    assert len(rows) == 1 and "PM sign-off withdrawn" in rows[0].action_description
    assert "Quality" not in rows[0].action_description
    assert any("Sign again for offer v2" in n.title for n in notes)
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 200, res.text
    # NEGATIVE: approval waits for the PM's new signature
    assert res.json()["status"] == "quoted"
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=pm)).json()
    rows = tasks if isinstance(tasks, list) else tasks.get("tasks", [])
    row = next(t for t in rows if t["kind"] == "sign_off" and t["change_id"] == cid)
    assert (row["side"], row["offer_version"], row["prev_version"]) == ("pm", 2, 1)
    assert row["offer_total"] > 0 and row["margin_delta_pts"] is not None
    assert row["assumed_open"] == 0
    r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": "pm"}, headers=pm)
    assert r.json()["status"] == "approved"


async def test_a_part_index_change_withdraws_quality_too(
        client, session_factory, seed, offer_world, quality_member):
    from app.models.part import PartRevision
    cid, sales, pm, q, (part_id, item_id) = await _signed_v1(
        client, session_factory, seed, offer_world, with_part=True)
    async with session_factory() as s:
        d = PartRevision(part_id=part_id, revision_name="4", phase="official",
                         customer_index="D", source="customer", created_by=seed["admin_id"])
        s.add(d)
        await s.flush()
        item = await s.get(ChangeImpactedItem, item_id)
        item.resulting_revision_id = d.id
        await s.commit()
    await _v2_with_discount(client, cid, sales, -5)
    async with session_factory() as s:
        row = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "signoff_withdrawn"))).scalar_one()
    assert "PM and Quality sign-off withdrawn" in row.action_description
    assert (await _answer(client, cid, sales, _YES)).status_code == 200
    # Quality's row carries no prices (Quality signs without price)
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=q)).json()
    rows = tasks if isinstance(tasks, list) else tasks.get("tasks", [])
    qrow = next(t for t in rows if t["kind"] == "sign_off" and t["change_id"] == cid)
    assert qrow["side"] == "quality" and "offer_total" not in qrow


# ---------------------------------------------------------------------------
# §6 supplements after approval
# ---------------------------------------------------------------------------
@pytest.fixture
async def approved(client, quoted):
    from tests.conftest import login, ENGINEER_PASSWORD
    cid = quoted["change_id"]
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    q = await login(client, "off-quality@test.io", ENGINEER_PASSWORD)
    assert (await _answer(client, cid, sales, _YES)).status_code == 200
    for role, who in (("pm", pm), ("quality", q)):
        r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": role}, headers=who)
    assert r.json()["status"] == "approved", r.text
    return {**quoted, "sales": sales, "pm": pm, "q": q}


async def _raise_position(session_factory, world, to):
    from app.models.change_cost import CostingPosition
    async with session_factory() as s:
        pos = await s.get(CostingPosition, world["position_id"])
        pos.est_cost = to
        await s.commit()


async def _supplement(client, cid, sales):
    res = await client.post(_url(cid), headers=sales)
    assert res.status_code == 201, res.text
    return res.json()


async def test_supplement_prices_only_what_changed_and_keeps_the_status(
        client, approved, session_factory):
    from app.models.change import ChangeRequest
    cid, sales = approved["change_id"], approved["sales"]
    s1 = await _supplement(client, cid, sales)
    assert s1["kind"] == "supplement" and s1["data"]["cost_lines"] == []
    # NEGATIVE: nothing changed, nothing to send
    res = await client.post(_url(cid, f"/{s1['id']}/send"),
                            json={"change_note": "nothing"}, headers=sales)
    assert res.status_code == 400 and "zero" in res.json()["detail"]
    await _raise_position(session_factory, approved, 1500)
    res = await client.post(_url(cid, f"/{s1['id']}/refresh"), headers=sales)
    assert res.status_code == 200, res.text
    lines = res.json()["data"]["cost_lines"]
    assert [(l["key"], l["amount"]) for l in lines] == [
        (f"pos:{approved['position_id']}", 500.0)]
    res = await client.post(_url(cid, f"/{s1['id']}/send"),
                            json={"change_note": "Insert rework quoted higher"}, headers=sales)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, cid)
        assert (ch.status, ch.price_open, ch.customer_response) == ("approved", True, "accepted")
        assert ch.quoted_price == 1000         # the quote stays what it was
        rows = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
    assert "signoff_withdrawn" in rows        # PM signs the supplement again
    # Sales chases the answer, in approved
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    rows = tasks if isinstance(tasks, list) else tasks.get("tasks", [])
    assert any(t["kind"] == "customer_response" and t.get("supplement_version") == s1["version"]
               for t in rows)
    # NEGATIVE: the PM's re-sign waits until the customer accepts
    pm_rows = (await client.get("/api/v1/changes/my-tasks", headers=approved["pm"])).json()
    pm_rows = pm_rows if isinstance(pm_rows, list) else pm_rows.get("tasks", [])
    assert not any(t["kind"] == "sign_off" and t["change_id"] == cid for t in pm_rows)
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["status"], body["price_open"]) == ("approved", False)
    pm_rows = (await client.get("/api/v1/changes/my-tasks", headers=approved["pm"])).json()
    pm_rows = pm_rows if isinstance(pm_rows, list) else pm_rows.get("tasks", [])
    assert any(t["kind"] == "sign_off" and t["change_id"] == cid and t["side"] == "pm"
               for t in pm_rows)


async def test_a_declined_supplement_leaves_the_price_open_for_absorb(
        client, approved, session_factory):
    cid, sales = approved["change_id"], approved["sales"]
    await _raise_position(session_factory, approved, 1300)
    s1 = await _supplement(client, cid, sales)
    assert (await client.post(_url(cid, f"/{s1['id']}/send"),
                              json={"change_note": "Rework higher"},
                              headers=sales)).status_code == 200
    res = await _answer(client, cid, sales, {"response": "declined",
                                             "ref": "Mail 15 Oct, buyer refuses"})
    assert res.status_code == 200, res.text
    assert (res.json()["status"], res.json()["price_open"]) == ("approved", True)
    res = await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "goodwill", "note": "Small amount, goodwill on the program"},
        headers=sales)
    assert res.status_code == 200, res.text


async def test_a_negative_supplement_needs_a_reason_and_the_ok(client, approved, session_factory):
    from app.models.change import ChangeRequest, ChangeTransitionDeviation
    cid, sales, pm = approved["change_id"], approved["sales"], approved["pm"]
    await _raise_position(session_factory, approved, 800)
    s1 = await _supplement(client, cid, sales)
    assert s1["data"]["cost_lines"][0]["amount"] == -200.0
    assert (await client.post(_url(cid, f"/{s1['id']}/send"),
                              json={"change_note": "Insert cheaper"},
                              headers=sales)).status_code == 200
    res = await _answer(client, cid, sales, _YES)
    assert res.status_code == 400 and "lowers the accepted total" in res.json()["detail"]
    res = await _answer(client, cid, sales, {**_YES, "price_drop_code": "error",
                                             "price_drop_note": "Rework was double counted in v1"})
    assert res.status_code == 200, res.text
    assert res.json()["price_open"] is True     # waits for the OK
    async with session_factory() as s:
        dev = (await s.execute(select(ChangeTransitionDeviation).where(
            ChangeTransitionDeviation.change_id == cid,
            ChangeTransitionDeviation.guard_key == "price_drop"))).scalar_one()
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev.id}/decide",
                          json={"decision": "approved"}, headers=pm)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).price_open is False


async def test_only_offer_writers_start_a_supplement_and_switch_off_refuses(
        client, approved, monkeypatch):
    cid = approved["change_id"]
    # NEGATIVE: Quality signs, it does not write offers
    res = await client.post(_url(cid), headers=approved["q"])
    assert res.status_code == 403
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    res = await client.post(_url(cid), headers=approved["sales"])
    assert res.status_code == 400 and "accepted" in res.json()["detail"]


# ---------------------------------------------------------------------------
# §6 [R3] the scope change card
# ---------------------------------------------------------------------------
async def _route_tool(session_factory, world):
    from app.models.change import ChangeAssessment
    from datetime import datetime as _dt
    async with session_factory() as s:
        s.add(ChangeAssessment(change_id=world["change_id"],
                               department_id=world["depts"]["Tool Engineer"],
                               verdict="feasible", rasic_letter="R", status="submitted",
                               submitted_at=_dt.utcnow()))
        await s.commit()


def _scope(cid, tail=""):
    return f"/api/v1/changes/{cid}/scope-changes{tail}"


async def _card(client, cid, sales, **over):
    res = await client.post(_scope(cid), json={
        "what": "Second variant with a grained surface", "part_number": "886.198",
        "ref": "Mail 15 Oct from the buyer", **over}, headers=sales)
    assert res.status_code == 200, res.text
    return res.json()[-1]


async def _tasks(client, auth):
    rows = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    return rows if isinstance(rows, list) else rows.get("tasks", [])


async def test_scope_change_card_runs_requested_recosted_accepted(client, quoted, session_factory):
    from tests.conftest import login, ENGINEER_PASSWORD
    cid = quoted["change_id"]
    await _route_tool(session_factory, quoted)
    sales, pm, tool = (await _auth(client, "sales"), await _auth(client, "pm"),
                       await _auth(client, "tool"))
    q = await login(client, "off-quality@test.io", ENGINEER_PASSWORD)
    # NEGATIVE: not Sales nor the run team; evidence that says nothing
    assert (await client.post(_scope(cid), json={"what": "a variant", "ref": "Mail 15 Oct"},
                              headers=tool)).status_code == 403
    res = await client.post(_scope(cid), json={"what": "a variant", "ref": "ok"}, headers=sales)
    assert res.status_code == 400
    card = await _card(client, cid, sales)
    assert card["status"] == "requested"
    assert any(t["kind"] == "scope_change_decide" for t in await _tasks(client, pm))
    # NEGATIVE: Sales does not decide it; a department not routed is refused
    r = await client.post(_scope(cid, f"/{card['id']}/decide"),
                          json={"decision": "accept", "department_ids": [quoted["depts"]["Tool Engineer"]]},
                          headers=sales)
    assert r.status_code == 403
    r = await client.post(_scope(cid, f"/{card['id']}/decide"),
                          json={"decision": "accept", "department_ids": [quoted["depts"]["Sales"]]},
                          headers=pm)
    assert r.status_code == 400
    r = await client.post(_scope(cid, f"/{card['id']}/decide"),
                          json={"decision": "accept", "department_ids": [quoted["depts"]["Tool Engineer"]]},
                          headers=pm)
    assert r.status_code == 200, r.text
    assert r.json()[0]["waiting_for"] == ["Tool Engineer"]
    assert any(t["kind"] == "costing_update" and t.get("scope_change_id") == card["id"]
               for t in await _tasks(client, tool))
    # an offer sent while re-costing runs says so, and covers nothing
    v2 = await _v2_with_discount(client, cid, sales, -5)
    assert any(f["label"] == "Scope change 886.198: subject to final costing"
               for f in v2["data"]["free_fields"])
    # accepted and signed, the open card still holds the approval
    assert (await _answer(client, cid, sales, _YES)).status_code == 200
    for role, who in (("pm", pm), ("quality", q)):
        r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": role}, headers=who)
    assert r.json()["status"] == "quoted"     # NEGATIVE: scope change uncovered
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    assert "scope_change_uncovered" in {i.get("rule") for i in ch["next_step"]["items"]}


async def test_scope_change_ready_goes_into_the_next_offer(client, quoted, session_factory):
    cid = quoted["change_id"]
    await _route_tool(session_factory, quoted)
    sales, pm, tool = (await _auth(client, "sales"), await _auth(client, "pm"),
                       await _auth(client, "tool"))
    card = await _card(client, cid, sales)
    tid = quoted["depts"]["Tool Engineer"]
    await client.post(_scope(cid, f"/{card['id']}/decide"),
                      json={"decision": "accept", "department_ids": [tid]}, headers=pm)
    # NEGATIVE: Sales does not mark Tool Engineer's re-costing done
    r = await client.post(_scope(cid, f"/{card['id']}/recosted"),
                          json={"department_id": tid}, headers=sales)
    assert r.status_code == 403
    r = await client.post(_scope(cid, f"/{card['id']}/recosted"),
                          json={"department_id": tid}, headers=tool)
    assert r.status_code == 200 and r.json()[0]["status"] == "ready"
    assert any(t["kind"] == "revise_offer" for t in await _tasks(client, sales))
    await _v2_with_discount(client, cid, sales, -5)
    cards = (await client.get(_scope(cid), headers=sales)).json()
    assert cards[0]["status"] == "offered"
    assert (await _answer(client, cid, sales, _YES)).status_code == 200
    assert (await client.get(_scope(cid), headers=sales)).json()[0]["status"] == "accepted"


async def test_refused_card_leaves_sales_to_tell_the_customer(client, quoted):
    cid = quoted["change_id"]
    sales, pm = await _auth(client, "sales"), await _auth(client, "pm")
    card = await _card(client, cid, sales)
    r = await client.post(_scope(cid, f"/{card['id']}/decide"),
                          json={"decision": "refuse"}, headers=pm)
    assert r.status_code == 400               # NEGATIVE: a refusal says why
    r = await client.post(_scope(cid, f"/{card['id']}/decide"),
                          json={"decision": "refuse", "note": "Not feasible in this tool"},
                          headers=pm)
    assert r.status_code == 200
    assert any(t["kind"] == "scope_change_tell" for t in await _tasks(client, sales))
    r = await client.post(_scope(cid, f"/{card['id']}/told"),
                          json={"ref": "Mail 16 Oct to the buyer"}, headers=sales)
    assert r.status_code == 200
    assert not any(t["kind"] == "scope_change_tell" for t in await _tasks(client, sales))


async def test_after_approval_a_card_opens_the_price_and_an_added_part_is_its_own_change(
        client, approved, session_factory):
    from app.models.change import ChangeRequest
    cid, sales, pm = approved["change_id"], approved["sales"], approved["pm"]
    card = await _card(client, cid, sales)
    assert card["post_accept"] is True
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    assert ch["price_open"] is True
    r = await client.post(_scope(cid, f"/{card['id']}/decide"),
                          json={"decision": "new_change"}, headers=pm)
    assert r.status_code == 200, r.text
    new_id = r.json()[0]["new_change_id"]
    async with session_factory() as s:
        new = await s.get(ChangeRequest, new_id)
        old = await s.get(ChangeRequest, cid)
        assert (new.status, new.related_change_id, new.customer_relevant) == ("captured", cid, True)
        assert old.price_open is False          # the card that opened it is moved


async def test_po_differs_opens_a_card_that_holds_implementation(client, quoted):
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    res = await _answer(client, cid, sales, {**_YES, "po_match": "no",
                                             "differs": "PO also lists 886.199"})
    assert res.status_code == 200, res.text
    cards = (await client.get(_scope(cid), headers=sales)).json()
    assert (cards[0]["kind"], cards[0]["status"], cards[0]["post_accept"]) == (
        "po_differs", "requested", True)


async def test_scope_cards_switch_off(client, quoted, monkeypatch):
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    cid = quoted["change_id"]
    sales = await _auth(client, "sales")
    res = await client.post(_scope(cid), json={"what": "a variant", "ref": "Mail 15 Oct"},
                            headers=sales)
    assert res.status_code == 400 and "switched off" in res.json()["detail"]


# ---------------------------------------------------------------------------
# §7a start at risk (P8: urgent only, PM member approves, Quality's line)
# ---------------------------------------------------------------------------
@pytest.fixture
async def urgent(session_factory, offer_world, quality_member):
    from datetime import datetime as _dt, timedelta as _td
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, offer_world["change_id"])
        ch.priority = "critical"
        ch.release_due_date = _dt.utcnow() + _td(days=40)
        await s.commit()
    return offer_world


def _sar(cid, tail=""):
    return f"/api/v1/changes/{cid}/start-at-risk{tail}"


async def _quality(client):
    from tests.conftest import login, ENGINEER_PASSWORD
    return await login(client, "off-quality@test.io", ENGINEER_PASSWORD)


async def test_start_at_risk_asks_quality_then_a_pm_member(client, urgent, session_factory):
    from app.models.change import ChangeRequest
    cid = urgent["change_id"]
    sales, pm, tool = (await _auth(client, "sales"), await _auth(client, "pm"),
                       await _auth(client, "tool"))
    q = await _quality(client)
    # NEGATIVE: not Sales nor the run team; a go-ahead that says nothing
    assert (await client.post(_sar(cid), json={"ref": "Mail 15 Oct go"}, headers=tool)).status_code == 403
    assert (await client.post(_sar(cid), json={"ref": "ok"}, headers=sales)).status_code == 400
    r = await client.post(_sar(cid), json={"ref": "Mail 15 Oct: start tooling now, PO follows"},
                          headers=sales)
    assert r.status_code == 200, r.text
    assert any(t["kind"] == "start_at_risk_quality" for t in await _tasks(client, q))
    # NEGATIVE: no approval before Quality's line; Sales does not write it
    r = await client.post(_sar(cid, "/approve"), headers=pm)
    assert r.status_code == 400 and "Quality" in r.json()["detail"]
    assert (await client.post(_sar(cid, "/quality"), json={"note": "first lot 100 % checked"},
                              headers=sales)).status_code == 403
    assert (await client.post(_sar(cid, "/quality"), json={"note": "ok"},
                              headers=q)).status_code == 400
    r = await client.post(_sar(cid, "/quality"),
                          json={"note": "No PPAP before SOP; first lot 100 % checked"}, headers=q)
    assert r.status_code == 200, r.text
    assert any(t["kind"] == "start_at_risk_approve" for t in await _tasks(client, pm))
    # NEGATIVE: Quality does not approve it
    assert (await client.post(_sar(cid, "/approve"), headers=q)).status_code == 403
    r = await client.post(_sar(cid, "/approve"), headers=pm)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, cid)
        assert (ch.status, ch.price_open, ch.customer_response) == ("approved", True, "pending")
    # both sign-off rows come at once (HARD #9 holds them at release)
    assert any(t["kind"] == "sign_off" and t["side"] == "pm" and t["change_id"] == cid
               for t in await _tasks(client, pm))
    assert any(t["kind"] == "sign_off" and t["side"] == "quality" and t["change_id"] == cid
               for t in await _tasks(client, q))
    # Sales sends the offer: still an offer, the change stays approved
    assert any(t["kind"] == "create_quote" and t["change_id"] == cid
               for t in await _tasks(client, sales))
    o = await _create(client, sales, cid)
    assert o["kind"] == "offer"
    await _no_timing(client, sales, cid, o["id"])
    r = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert r.status_code == 200, r.text
    r = await _answer(client, cid, sales, _YES)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["price_open"], r.json()["customer_response"]) == (
        "approved", False, "accepted")


async def test_start_at_risk_never_by_the_asker_and_urgent_only(client, urgent, session_factory):
    from app.models.change import ChangeRequest
    from tests.conftest import login
    cid = urgent["change_id"]
    pm, q = await _auth(client, "pm"), await _quality(client)
    assert (await client.post(_sar(cid), json={"ref": "Mail 15 Oct: start now, PO follows"},
                              headers=pm)).status_code == 200
    await client.post(_sar(cid, "/quality"), json={"note": "No PPAP before SOP, lot checked"},
                      headers=q)
    r = await client.post(_sar(cid, "/approve"), headers=pm)
    assert r.status_code == 403 and "4-eyes" in r.json()["detail"]
    admin = await login(client, "admin@test.io")
    r = await client.post(_sar(cid, "/approve"), headers=admin)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, cid)
        ch.status, ch.priority, ch.start_at_risk_approved_at = "quoting", "medium", None
        ch.start_at_risk_requested_at = None
        await s.commit()
    r = await client.post(_sar(cid), json={"ref": "Mail 15 Oct: start now, PO follows"}, headers=pm)
    assert r.status_code == 400 and "urgent" in r.json()["detail"]


async def test_declined_after_a_start_at_risk_keeps_the_price_open(client, urgent, session_factory):
    from app.models.change import ChangeRequest
    cid = urgent["change_id"]
    sales, pm, q = await _auth(client, "sales"), await _auth(client, "pm"), await _quality(client)
    await client.post(_sar(cid), json={"ref": "Mail 15 Oct: start now, PO follows"}, headers=sales)
    await client.post(_sar(cid, "/quality"), json={"note": "No PPAP before SOP, lot checked"}, headers=q)
    assert (await client.post(_sar(cid, "/approve"), headers=pm)).status_code == 200
    o = await _create(client, sales, cid)
    await _no_timing(client, sales, cid, o["id"])
    assert (await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)).status_code == 200
    r = await _answer(client, cid, sales, {"response": "declined", "ref": "Mail 20 Oct: too high"})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["price_open"]) == ("approved", True)


async def test_start_at_risk_switch_off(client, urgent, monkeypatch):
    monkeypatch.setattr(cm_switches, "START_AT_RISK", False)
    cid = urgent["change_id"]
    sales = await _auth(client, "sales")
    r = await client.post(_sar(cid), json={"ref": "Mail 15 Oct: start now, PO follows"}, headers=sales)
    assert r.status_code == 400 and "switched off" in r.json()["detail"]


async def _started_at_risk(client, cid, sales, pm, q):
    r = await client.post(_sar(cid), json={"ref": "Mail 15 Oct: start now, PO follows"}, headers=sales)
    assert r.status_code == 200, r.text
    r = await client.post(_sar(cid, "/quality"), json={"note": "No PPAP before SOP, lot checked"},
                          headers=q)
    assert r.status_code == 200, r.text
    r = await client.post(_sar(cid, "/approve"), headers=pm)
    assert r.status_code == 200, r.text


async def test_start_at_risk_from_quoted_then_the_customer_accepts_v1(
        client, urgent, session_factory):
    cid = urgent["change_id"]
    sales, pm, q = await _auth(client, "sales"), await _auth(client, "pm"), await _quality(client)
    o = await _create(client, sales, cid)
    await _no_timing(client, sales, cid, o["id"])
    assert (await client.post(_url(cid, f"/{o['id']}/send"), json={},
                              headers=sales)).status_code == 200
    await _started_at_risk(client, cid, sales, pm, q)
    # Sales chases the answer to v1 in approved
    assert any(t["kind"] == "customer_response" and t["change_id"] == cid
               for t in await _tasks(client, sales))
    r = await _answer(client, cid, sales, _YES)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["price_open"], r.json()["customer_response"]) == (
        "approved", False, "accepted")


async def test_an_at_risk_acceptance_of_a_lower_version_waits_for_the_ok(
        client, urgent, session_factory):
    from app.models.change import ChangeRequest, ChangeTransitionDeviation
    cid = urgent["change_id"]
    sales, pm, q = await _auth(client, "sales"), await _auth(client, "pm"), await _quality(client)
    o = await _create(client, sales, cid)
    await _no_timing(client, sales, cid, o["id"])
    assert (await client.post(_url(cid, f"/{o['id']}/send"), json={},
                              headers=sales)).status_code == 200
    await _started_at_risk(client, cid, sales, pm, q)
    await _v2_with_discount(client, cid, sales, 10)
    r = await _answer(client, cid, sales, _YES)
    assert r.status_code == 400 and "below v1" in r.json()["detail"]
    r = await _answer(client, cid, sales, {
        **_YES, "price_drop_code": "competitor",
        "price_drop_note": "Competitor offered 8 % less, mail of 13 Oct"})
    assert r.status_code == 200, r.text
    # NEGATIVE: the lower price is not settled before the PM's OK
    assert (r.json()["status"], r.json()["price_open"]) == ("approved", True)
    async with session_factory() as s:
        dev = (await s.execute(select(ChangeTransitionDeviation).where(
            ChangeTransitionDeviation.change_id == cid,
            ChangeTransitionDeviation.guard_key == "price_drop"))).scalar_one()
    assert (dev.status, dev.to_status) == ("pending", "closed")
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev.id}/decide",
                          json={"decision": "approved"}, headers=pm)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).price_open is False


async def test_a_revised_supplement_below_the_one_it_revised_needs_the_ok(
        client, approved, session_factory):
    from app.models.change import ChangeRequest, ChangeTransitionDeviation
    cid, sales, pm = approved["change_id"], approved["sales"], approved["pm"]
    await _raise_position(session_factory, approved, 1500)
    s1 = await _supplement(client, cid, sales)
    assert (await client.post(_url(cid, f"/{s1['id']}/send"),
                              json={"change_note": "Rework higher"},
                              headers=sales)).status_code == 200
    await _raise_position(session_factory, approved, 1200)
    s2 = await _supplement(client, cid, sales)
    assert s2["data"]["cost_lines"][0]["amount"] == 200.0
    assert (await client.post(_url(cid, f"/{s2['id']}/send"),
                              json={"change_note": "Rework cheaper after all"},
                              headers=sales)).status_code == 200
    # NEGATIVE: +200 after +500 is a discount, even though it is positive
    r = await _answer(client, cid, sales, _YES)
    assert r.status_code == 400 and f"below v{s1['version']}" in r.json()["detail"]
    r = await _answer(client, cid, sales, {**_YES, "price_drop_code": "goodwill",
                                           "price_drop_note": "Buyer asked, we meet halfway on rework"})
    assert r.status_code == 200, r.text
    assert r.json()["price_open"] is True
    async with session_factory() as s:
        dev = (await s.execute(select(ChangeTransitionDeviation).where(
            ChangeTransitionDeviation.change_id == cid,
            ChangeTransitionDeviation.guard_key == "price_drop"))).scalar_one()
    assert dev.to_status == "closed"
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev.id}/decide",
                          json={"decision": "approved"}, headers=pm)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).price_open is False
