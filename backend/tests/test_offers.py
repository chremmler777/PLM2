"""The customer offer: versions seeded from the costing, priced by the server,
sent (quoting -> quoted), valid 30 days from receipt, accepted or declined.

Pinned here: v1 is seeded from the summation and the risk register; one draft
at a time; PATCH merges top-level dicts and replaces lists; the totals follow
the business rule to the cent; sending moves the change and stamps the price;
a new version must say what changed and carries a diff; an expired offer is
accepted only with a reason; the PDF renders for a draft and a sent version.
"""
from datetime import date, datetime, timedelta

import pytest

from app.utils.clock import business_today
from app.models.change import ChangeConcern, ChangeRequest
from app.models.change_cost import CostingPosition
from app.models.change_offer import ChangeOffer
from app.models.workflow import Department, UserDepartment
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def offer_world(session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        depts = {}
        for name in ("Sales", "Project Manager", "Tool Engineer"):
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for key, dept in (("sales", "Sales"), ("pm", "Project Manager"),
                          ("tool", "Tool Engineer")):
            u = User(organization_id=seed["org_id"], username=f"off-{key}",
                     email=f"off-{key}@test.io", full_name=f"Offer {key}",
                     role="engineer",
                     hashed_password=get_password_hash("role-secret-1"),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[dept]))
            users[key] = u.id
        change = ChangeRequest(
            change_number="C-O-1", title="offer me", reason="thicker rib",
            description="Rib +0.5 mm", change_type="physical_part",
            project_id=seed["project_id"], raised_by=users["sales"],
            customer_relevant=True, status="quoting")
        s.add(change)
        await s.flush()
        pos = CostingPosition(
            change_id=change.id, department_id=depts["Tool Engineer"],
            label="Insert rework", kind="external", pricing="estimate",
            est_cost=1000, vendor_name="Hasco", lead_time_days=10,
            created_by=users["tool"])
        s.add(pos)
        s.add(ChangeConcern(change_id=change.id, kind="risk", note="fill at rib end",
                            risk_type="fill_issue", severity=3,
                            department_id=depts["Tool Engineer"],
                            raised_by=users["tool"]))
        await s.commit()
        return {"change_id": change.id, "users": users, "depts": depts,
                "position_id": pos.id}


async def _auth(client, key):
    return await login(client, f"off-{key}@test.io", ENGINEER_PASSWORD)


def _url(cid, tail=""):
    return f"/api/v1/changes/{cid}/offers{tail}"


async def _create(client, auth, cid):
    res = await client.post(_url(cid), headers=auth)
    assert res.status_code == 201, res.text
    return res.json()


async def _seed_quote_plan(client, auth, cid):
    res = await client.post(f"/api/v1/changes/{cid}/plan/seed",
                            json={"plan": "quote"}, headers=auth)
    assert res.status_code == 200, res.text


async def test_v1_is_seeded_from_costing_and_register(client, offer_world):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    await _seed_quote_plan(client, sales, cid)
    o = await _create(client, sales, cid)
    assert (o["version"], o["status"], o["currency"]) == (1, "draft", "EUR")
    d = o["data"]
    # the project name is not an addressee: Sales types the company
    assert d["recipient"]["company"] == ""
    assert "recipient_missing" in {w["code"] for w in o["warnings"]}
    assert d["scope_text"] == "Rib +0.5 mm" and d["customer_note"] == ""
    assert d["subject"] == "Offer for engineering change C-O-1: offer me"
    line = next(l for l in d["cost_lines"]
                if l["key"] == f"pos:{offer_world['position_id']}")
    assert line["amount"] == line["source_amount"] == 1000
    assert line["label"] == "Insert rework (Hasco)" and line["category"] == "external"
    assert [f["key"] for f in d["factors"]] == [
        "overhead", "margin", "engineering_fee", "sampling_ppap",
        "freight_packaging", "expedite", "discount"]
    assert not any(f["enabled"] for f in d["factors"])
    assert next(f for f in d["factors"] if f["key"] == "discount")["sign"] == -1
    risk = d["risks"][0]
    assert (risk["label"], risk["severity"], risk["show"], risk["value"]) == \
        ("Fill issue", 3, False, 0)  # Sales opts in (final walk P2-7)
    assert d["changeover"]["mode"] == "running_change"
    assert d["timing"]["include"] is True
    assert d["timing"]["weeks_from_order"] >= 1
    assert "Start of production (change)" in [m["label"] for m in d["timing"]["milestones"]]
    assert d["terms"]["payment"] == "30 days net"
    assert o["totals"]["base"] == 1000 and o["totals"]["internal_cost"] == 1000
    assert o["diff"] is None
    # not shown by default, so no "shown without a surcharge" warning yet
    assert "high_risk_unpriced" not in {w["code"] for w in o["warnings"]}


async def test_one_draft_at_a_time_and_rights(client, offer_world):
    cid = offer_world["change_id"]
    sales, pm, tool = (await _auth(client, "sales"), await _auth(client, "pm"),
                       await _auth(client, "tool"))
    o = await _create(client, sales, cid)
    res = await client.post(_url(cid), headers=sales)
    assert res.status_code == 409
    assert res.json()["detail"]["draft_id"] == o["id"]
    # PM reads, does not write; others see no prices at all
    assert (await client.get(_url(cid), headers=pm)).status_code == 200
    assert (await client.patch(_url(cid, f"/{o['id']}"), json={"data": {}},
                               headers=pm)).status_code == 403
    assert (await client.get(_url(cid), headers=tool)).status_code == 403
    assert (await client.get(_url(cid, f"/{o['id']}/pdf"),
                             headers=tool)).status_code == 403


async def test_patch_merges_top_level(client, offer_world):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    res = await client.patch(_url(cid, f"/{o['id']}"), json={
        "data": {"terms": {"incoterms": "FCA"},
                 "factors": [{"key": "margin", "label": "Margin", "type": "pct",
                              "value": 10, "sign": 1, "enabled": True}]},
        "currency": "usd"}, headers=sales)
    assert res.status_code == 200, res.text
    d = res.json()["data"]
    assert d["terms"] == {"payment": "30 days net", "incoterms": "FCA",
                          "delivery": "", "notes": ""}
    assert [f["key"] for f in d["factors"]] == ["margin"]     # list replaced
    assert res.json()["currency"] == "USD"
    assert res.json()["totals"]["total_one_time"] == 1100
    res = await client.patch(_url(cid, f"/{o['id']}"),
                             json={"data": {"cbd_mode": "fancy"}}, headers=sales)
    assert res.status_code == 400


async def test_totals_math(client, offer_world):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "cost_lines": [
            {"key": "a", "label": "A", "category": "internal", "amount": 1000,
             "source_amount": 1000, "include": True},
            {"key": "b", "label": "B", "category": "external", "amount": 500,
             "source_amount": 500, "include": False}],
        "factors": [
            {"key": "overhead", "label": "Overhead", "type": "pct", "value": 10,
             "sign": 1, "enabled": True},
            {"key": "engineering_fee", "label": "Fee", "type": "amount",
             "value": 200, "sign": 1, "enabled": True},
            {"key": "discount", "label": "Discount", "type": "pct", "value": 5,
             "sign": -1, "enabled": True},
            {"key": "margin", "label": "Margin", "type": "pct", "value": 50,
             "sign": 1, "enabled": False}],
        "risks": [{"concern_id": 1, "label": "r1", "type": "pct", "value": 2},
                  {"concern_id": 2, "label": "r2", "type": "amount", "value": 50}],
        "changeover": {"mode": "customer_pays_scrap", "scrap_qty": 100,
                       "scrap_unit_price": 2.5},
        "free_fields": [{"label": "Tooling transport", "value": "", "amount": 30},
                        {"label": "Note", "value": "text only"}],
        "piece_price": {"enabled": True, "annual_volume": 10000,
                        "rows": [{"label": "material", "driver": "weight",
                                  "delta_per_piece": 0.01},
                                 {"label": "cycle", "driver": "time",
                                  "delta_per_piece": 0.02}]},
    }}, headers=sales)
    assert res.status_code == 200, res.text
    t = res.json()["totals"]
    assert t["base"] == 1000
    assert [f["amount"] for f in t["factors"]] == [100, 200, -50]
    assert t["risks_total"] == 70
    assert t["scrap"] == 250
    assert t["free"] == 30
    assert t["total_one_time"] == 1600
    assert t["piece_price_delta"] == 0.03
    assert t["annual_effect"] == 300
    assert t["internal_cost"] == 1000
    assert t["margin_abs"] == 600 and t["margin_pct"] == 37.5


async def test_send_moves_to_quoted_and_versions(client, offer_world, session_factory):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    # timing included, but no quote plan yet
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 400 and "quote plan" in res.json()["detail"]
    await _seed_quote_plan(client, sales, cid)
    today = business_today()
    tomorrow = (today + timedelta(days=3)).isoformat()   # beyond any UTC offset + 1 day
    # the customer cannot receive it tomorrow, nor before it was sent
    res = await client.post(_url(cid, f"/{o['id']}/send"),
                            json={"received_at": tomorrow}, headers=sales)
    assert res.status_code == 400 and "future" in res.json()["detail"]
    # recorded after the fact is fine, two months back is not
    res = await client.post(_url(cid, f"/{o['id']}/send"),
                            json={"received_at": (today - timedelta(days=61)).isoformat()},
                            headers=sales)
    assert res.status_code == 400 and "days ago" in res.json()["detail"]
    res = await client.post(_url(cid, f"/{o['id']}/send"),
                            json={"received_at": today.isoformat()}, headers=sales)
    assert res.status_code == 200, res.text
    v1 = res.json()
    assert v1["status"] == "sent" and v1["received_at"] == today.isoformat()
    assert v1["valid_until"] == (today + timedelta(days=30)).isoformat()
    assert v1["sent_by_name"] == "Offer sales"
    change = (await client.get(f"/api/v1/changes/{cid}", headers=sales)).json()
    assert change["status"] == "quoted"
    assert change["quoted_price"] == 1000
    # a sent version is frozen
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {}}, headers=sales)
    assert res.status_code == 400

    # receipt date corrected: validity recomputed; not into the future
    res = await client.post(_url(cid, f"/{o['id']}/received"),
                            json={"received_at": tomorrow}, headers=sales)
    assert res.status_code == 400
    res = await client.post(_url(cid, f"/{o['id']}/received"),
                            json={"received_at": today.isoformat()}, headers=sales)
    assert res.status_code == 200
    assert res.json()["valid_until"] == (today + timedelta(days=30)).isoformat()

    v2 = await _create(client, sales, cid)
    assert v2["version"] == 2 and v2["data"]["subject"] == v1["data"]["subject"]
    res = await client.post(_url(cid, f"/{v2['id']}/received"),
                            json={"received_at": today.isoformat()}, headers=sales)
    assert res.status_code == 400                        # draft has no receipt
    await client.patch(_url(cid, f"/{v2['id']}"), json={"data": {
        "factors": [{"key": "discount", "label": "Discount", "type": "pct",
                     "value": 10, "sign": -1, "enabled": True}]}}, headers=sales)
    res = await client.post(_url(cid, f"/{v2['id']}/send"), json={}, headers=sales)
    assert res.status_code == 400 and "what changed" in res.json()["detail"]
    res = await client.post(_url(cid, f"/{v2['id']}/send"),
                            json={"change_note": "10% discount agreed"}, headers=sales)
    assert res.status_code == 200, res.text
    sent2 = res.json()
    assert sent2["totals"]["total_one_time"] == 900
    fields = {d["field"]: d for d in sent2["diff"]}
    assert fields["Total one-time"]["before"] == 1000
    assert fields["Total one-time"]["after"] == 900
    assert "Factor Discount" in fields
    offers = (await client.get(_url(cid), headers=sales)).json()
    assert [(x["version"], x["status"]) for x in offers] == [(2, "sent"), (1, "superseded")]
    change = (await client.get(f"/api/v1/changes/{cid}", headers=sales)).json()
    assert change["quoted_price"] == 900
    log = [e["action"] for e in (await client.get(
        f"/api/v1/changes/{cid}/changelog", headers=sales)).json()]
    assert log.count("offer_sent") == 2 and "offer_received" in log

    # negotiation rounds default to the latest sent version
    res = await client.post(f"/api/v1/changes/{cid}/negotiations",
                            json={"channel": "call", "note": "ok"}, headers=sales)
    assert res.status_code == 201 and res.json()["offer_id"] == v2["id"]


async def test_zero_total_is_refused(client, offer_world):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "cost_lines": [], "timing": {"include": False}}}, headers=sales)
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 400 and "greater than zero" in res.json()["detail"]


async def test_refresh_keeps_overrides(client, offer_world, session_factory):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    lines = o["data"]["cost_lines"]
    lines[0]["amount"] = 1500                   # Sales overrides the number
    lines.append({"key": "manual", "label": "Handling", "category": "other",
                  "amount": 40, "include": True})
    await client.patch(_url(cid, f"/{o['id']}"), json={"data": {"cost_lines": lines}},
                       headers=sales)
    async with session_factory() as s:
        p = await s.get(CostingPosition, offer_world["position_id"])
        p.est_cost = 1200
        await s.commit()
    got = (await client.get(_url(cid), headers=sales)).json()[0]
    assert "costing_changed" in {w["code"] for w in got["warnings"]}
    res = await client.post(_url(cid, f"/{o['id']}/refresh"), headers=sales)
    assert res.status_code == 200, res.text
    d = res.json()["data"]
    pos = next(l for l in d["cost_lines"] if l["key"].startswith("pos:"))
    assert pos["amount"] == 1500 and pos["source_amount"] == 1200
    assert any(l["key"] == "manual" for l in d["cost_lines"])


async def test_expired_offer_acceptance_needs_a_reason(client, offer_world,
                                                       session_factory):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    await client.patch(_url(cid, f"/{o['id']}"),
                       json={"data": {"timing": {"include": False}}}, headers=sales)
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        row = await s.get(ChangeOffer, o["id"])
        row.valid_until = business_today() - timedelta(days=1)
        await s.commit()
    got = (await client.get(_url(cid), headers=sales)).json()[0]
    assert got["expired"] is True and got["days_left"] == -1
    actions = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                                headers=sales)).json()["actions"]
    assert "offer_expiring" in {a["kind"] for a in actions}
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    assert "offer_expiring" in {t["kind"] for t in tasks}

    due = (datetime.utcnow() + timedelta(days=90)).isoformat()
    res = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due}, headers=sales)
    assert res.status_code == 400 and "expired" in res.json()["detail"]
    res = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due,
        "expired_override_reason": "customer confirmed by mail"}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["accepted_offer_id"] == o["id"]
    got = (await client.get(_url(cid), headers=sales)).json()[0]
    assert got["status"] == "accepted"
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=sales)).json()
    acc = next(e for e in log if e["action"] == "offer_accepted")
    assert "customer confirmed by mail" in acc["action_description"]


async def test_declined_marks_the_offer(client, offer_world):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    await client.patch(_url(cid, f"/{o['id']}"),
                       json={"data": {"timing": {"include": False}}}, headers=sales)
    await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "declined"}, headers=sales)
    assert res.status_code == 200, res.text
    assert (await client.get(_url(cid), headers=sales)).json()[0]["status"] == "declined"


async def test_pdf_for_draft_and_sent(client, offer_world):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    await _seed_quote_plan(client, sales, cid)
    o = await _create(client, sales, cid)
    res = await client.get(_url(cid, f"/{o['id']}/pdf"), headers=sales)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content[:4] == b"%PDF"
    assert "C-O-1-offer-v1.pdf" in res.headers["content-disposition"]
    await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "cbd_mode": "rough", "rough_description": "Rework — insert",
        "piece_price": {"enabled": True, "annual_volume": 1000,
                        "rows": [{"label": "m", "driver": "w", "delta_per_piece": 0.1}]},
        "changeover": {"mode": "customer_pays_scrap", "scrap_qty": 10,
                       "scrap_unit_price": 1}}}, headers=sales)
    await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    pm = await _auth(client, "pm")
    res = await client.get(_url(cid, f"/{o['id']}/pdf"), headers=pm)
    assert res.status_code == 200 and res.content[:4] == b"%PDF"


async def test_offer_build_action_at_quoting(client, offer_world):
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    actions = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                                headers=sales)).json()["actions"]
    build = next(a for a in actions if a["kind"] == "offer_build")
    assert build["target_tab"] == "offer"
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=sales)).json()
    row = next(t for t in tasks if t["kind"] == "create_quote")
    assert row["has_offer_draft"] is False and row["target_tab"] == "offer"


# ----------------------------------------------------------------------
# Review hardening
# ----------------------------------------------------------------------
async def _sent_v1(client, sales, cid):
    o = await _create(client, sales, cid)
    await client.patch(_url(cid, f"/{o['id']}"),
                       json={"data": {"timing": {"include": False}}}, headers=sales)
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 200, res.text
    return res.json()


async def test_customer_response_needs_sales_rights_and_quoted(client, offer_world):
    cid = offer_world["change_id"]
    sales, pm, tool = (await _auth(client, "sales"), await _auth(client, "pm"),
                       await _auth(client, "tool"))
    # still quoting: nothing is out with the customer yet
    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "declined"}, headers=sales)
    assert res.status_code == 400 and "quoted" in res.json()["detail"]
    await _sent_v1(client, sales, cid)
    for who in (pm, tool):
        res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                                json={"response": "declined"}, headers=who)
        assert res.status_code == 403


async def test_changelog_hides_prices_from_non_cost_roles(client, offer_world,
                                                          session_factory):
    from app.services.change_service import ChangeService
    cid = offer_world["change_id"]
    sales, tool = await _auth(client, "sales"), await _auth(client, "tool")
    await _sent_v1(client, sales, cid)
    # a row written by the old code, amount in the text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.append_changelog(
            s, change, "offer_sent",
            "Offer v1 sent: 1234.50 EUR, valid until 2026-10-30", 1)
        await ChangeService.append_changelog(
            s, change, "internal_costs_approved", "Internal costs approved (777.00)", 1)
        await s.commit()
    mine = [e for e in (await client.get(f"/api/v1/changes/{cid}/changelog",
                                         headers=sales)).json()]
    new = next(e for e in mine if e["action"] == "offer_sent")
    assert "1000" not in new["action_description"]          # new rows carry no amount
    assert any("1234.50" in e["action_description"] for e in mine)   # Sales sees legacy
    theirs = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=tool)).json()
    text = " ".join(e["action_description"] for e in theirs)
    assert "1234.50" not in text and "777" not in text
    assert "Offer v1 sent, valid until 2026-10-30" in text


async def test_offer_is_closed_after_acceptance(client, offer_world):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    v1 = await _sent_v1(client, sales, cid)
    due = (datetime.utcnow() + timedelta(days=90)).isoformat()
    res = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due}, headers=sales)
    assert res.status_code == 200, res.text
    res = await client.post(_url(cid), headers=sales)
    assert res.status_code == 400
    assert res.json()["detail"] == "The customer accepted v1; the offer is closed"
    res = await client.post(_url(cid, f"/{v1['id']}/send"), json={}, headers=sales)
    assert res.status_code == 400 and "offer is closed" in res.json()["detail"]


async def test_numbers_are_coerced_and_validated(client, offer_world):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "cost_lines": [{"key": "a", "label": "A", "category": "internal",
                        "amount": "1,000.50", "include": True}],
        "factors": [{"key": "margin", "label": "Margin", "type": "pct",
                     "value": "12.5", "sign": 1, "enabled": True}],
        "changeover": {"mode": "customer_pays_scrap", "scrap_qty": "10",
                       "scrap_unit_price": "2.5"},
        "free_fields": [{"label": "Text only", "value": "x"},
                        {"label": "Transport", "amount": "30"}],
        "piece_price": {"enabled": True, "annual_volume": "1000",
                        "rows": [{"label": "m", "delta_per_piece": "0.01"}]},
    }}, headers=sales)
    assert res.status_code == 200, res.text
    d, t = res.json()["data"], res.json()["totals"]
    assert d["cost_lines"][0]["amount"] == 1000.5
    assert d["factors"][0]["value"] == 12.5
    assert d["free_fields"][0].get("amount") is None and d["free_fields"][1]["amount"] == 30
    assert t["base"] == 1000.5 and t["scrap"] == 25 and t["free"] == 30
    assert t["annual_effect"] == 10
    for bad in ({"cost_lines": [{"key": "a", "amount": "lots"}]},
                {"factors": [{"key": "m", "value": {"x": 1}, "enabled": True}]},
                {"changeover": {"scrap_qty": "ten"}},
                {"cost_lines": ["not an object"]},
                {"piece_price": {"rows": [3]}},
                {"terms": "net 30"},
                # a decimal comma or a German thousands dot is ambiguous
                {"cost_lines": [{"key": "a", "amount": "1.000,50"}]},
                {"cost_lines": [{"key": "a", "amount": "1.000"}]},
                {"factors": [{"key": "m", "value": "12,5", "enabled": True}]}):
        res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": bad},
                                 headers=sales)
        assert res.status_code == 400, (bad, res.text)


async def test_negotiation_round_refers_to_a_sent_offer(client, offer_world):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    v1 = await _sent_v1(client, sales, cid)
    v2 = await _create(client, sales, cid)
    res = await client.post(f"/api/v1/changes/{cid}/negotiations", json={
        "channel": "call", "note": "on the draft", "offer_id": v2["id"]}, headers=sales)
    assert res.status_code == 400 and "draft" in res.json()["detail"]
    res = await client.post(f"/api/v1/changes/{cid}/negotiations", json={
        "channel": "call", "note": "on v1", "offer_id": v1["id"]}, headers=sales)
    assert res.status_code == 201 and res.json()["offer_id"] == v1["id"]


async def test_concurrent_create_answers_409_with_the_winner(
        client, offer_world, session_factory, monkeypatch):
    """Two POSTs that both passed the 'no draft yet' read: the loser hits the
    unique (change, version) key and gets the same 409 as the sequential case."""
    from app.services.offer_service import OfferService
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    first = await _create(client, sales, cid)

    async def blind(session, change):          # the loser read before the winner wrote
        return []
    monkeypatch.setattr(OfferService, "list_offers", staticmethod(blind))
    res = await client.post(_url(cid), headers=sales)
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["draft_id"] == first["id"]


# ----------------------------------------------------------------------
# PDF robustness (rendered directly, no HTTP)
# ----------------------------------------------------------------------
def _pdf_ctx(*, data=None, tasks=None, status="sent", totals=None):
    from app.services.offer_service import compute_totals, normalise
    d = normalise(data or {})
    return {
        "org_name": "Org & <Co>", "plant_name": "Plant", "plant_location": "Town",
        "project_name": "P", "change_number": "C-PDF-1", "title": "T <b>",
        "reason": "r & r", "description": "d" * 3000,
        "items": [{"number": "1<2", "name": "a & b", "index": "C"}],
        "offer": {"version": 2, "status": status, "currency": "EUR", "data": d,
                  "totals": totals or compute_totals(d, 100.0),
                  "change_note": "x < y & z", "sent_at": business_today(),
                  "valid_until": business_today() + timedelta(days=30)},
        "tasks": tasks or [],
    }


def _pages(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")


async def test_pdf_survives_string_and_garbage_numbers():
    from app.services.offer_pdf import render_offer_pdf
    ctx = _pdf_ctx(totals={"base": "1.000,50", "factors": [{"label": "F", "amount": "abc"}],
                           "risks_total": "12,5", "scrap": None, "free": "x",
                           "total_one_time": "1234,5", "piece_price_delta": "0,01",
                           "annual_effect": "n/a"})
    ctx["offer"]["data"].update({
        "cost_lines": [{"label": "A", "amount": "12,5", "include": True},
                       {"label": "B", "amount": "garbage", "include": True}],
        "changeover": {"mode": "customer_pays_scrap", "scrap_qty": "1.200",
                       "scrap_unit_price": "oops"},
        "piece_price": {"enabled": True, "annual_volume": "many",
                        "rows": [{"label": "m", "delta_per_piece": "0,01"}, "junk"]},
        "timing": {"include": True, "weeks_from_order": "twelve",
                   "milestones": [{"label": "M", "date": "not a date"}, 5]},
        "risks": [{"label": "R", "severity": "3", "show": True, "note": "n"}],
    })
    pdf = render_offer_pdf(ctx)
    assert pdf[:4] == b"%PDF"


async def test_pdf_splits_a_120_task_plan_over_pages():
    from app.services.offer_pdf import render_offer_pdf
    start = date(2026, 10, 5)
    tasks = [{"name": f"Task {i} & <x>", "lane": f"Lane {i % 5}", "kind": "work",
              "start": start + timedelta(days=i), "end": start + timedelta(days=i + 4),
              "duration": 0 if i % 10 == 0 else 4} for i in range(120)]
    pdf = render_offer_pdf(_pdf_ctx(data={"timing": {"include": True}}, tasks=tasks))
    assert pdf[:4] == b"%PDF" and _pages(pdf) >= 4


async def test_pdf_flows_a_20k_note_and_escapes_markup():
    from app.services.offer_pdf import render_offer_pdf
    note = ("Terms & conditions <apply> > never. " * 600)[:20000]
    pdf = render_offer_pdf(_pdf_ctx(data={
        "terms": {"notes": note, "payment": "<b>30</b> & net"},
        "intro": "Dear <customer> & team",
        "free_fields": [{"label": "L<1>", "value": "v & w" * 500}],
        "risks": [{"label": "R", "severity": 3, "show": True, "note": "n & <m>" * 400}],
    }, status="draft"))
    assert pdf[:4] == b"%PDF" and _pages(pdf) >= 4


async def test_send_refuses_a_quote_plan_with_errors_while_timing_is_included(
        client, offer_world, session_factory):
    from sqlalchemy import select
    from app.models.change_plan import ChangePlanTask
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    await _seed_quote_plan(client, sales, cid)
    o = await _create(client, sales, cid)
    async with session_factory() as s:
        rows = (await s.execute(select(ChangePlanTask).where(
            ChangePlanTask.change_id == cid, ChangePlanTask.plan == "quote")
            .order_by(ChangePlanTask.id))).scalars().all()
        first, second = rows[0], rows[1]
        old_name = first.name
        first.name = "  "
        second.duration_days = -3
        await s.commit()
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "The quote plan has 2 errors" in detail and "Timing" in detail
    # a dependency loop blocks as well
    async with session_factory() as s:
        first = await s.get(ChangePlanTask, rows[0].id)
        second = await s.get(ChangePlanTask, rows[1].id)
        first.name, second.duration_days = old_name, 2
        await s.commit()
    from app.models.change_plan import ChangePlanLink
    async with session_factory() as s:
        s.add(ChangePlanLink(change_id=cid, plan="quote", from_task_id=rows[0].id,
                             to_task_id=rows[0].id, type="FS", lag_days=0))
        await s.commit()
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 400 and "loop" in res.json()["detail"]
    # timing left out: the plan does not matter; the empty recipient company
    # is only a warning
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "timing": {"include": False}}}, headers=sales)
    assert res.status_code == 200 and res.json()["data"]["recipient"]["company"] == ""
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 200, res.text


async def test_quote_plan_ideas_are_kept_marked_and_drawn_hatched(
        client, offer_world, session_factory):
    """Idea blocks stay in the snapshot and the timing ("idea": True), never
    move the weeks from order, and the PDF draws them hatched with a key."""
    from sqlalchemy import select
    from app.models.change_plan import ChangePlanTask
    from app.services import offer_pdf
    from app.services.offer_service import OfferService
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    await _seed_quote_plan(client, sales, cid)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        before = await OfferService._quote_timing(s, change)
        rows = (await s.execute(select(ChangePlanTask).where(
            ChangePlanTask.change_id == cid, ChangePlanTask.plan == "quote")
            .order_by(ChangePlanTask.id))).scalars().all()
        last = max(rows, key=lambda t: t.start_date)
        seeded_ideas = {t.name for t in rows if t.is_idea}
        new_ideas = {"Extra trial", "Option gate"}
        s.add(ChangePlanTask(change_id=cid, plan="quote", name="Extra trial",
                             kind="sampling", is_idea=True, lane="Tooling",
                             start_date=last.start_date + timedelta(days=120),
                             created_by=offer_world["users"]["sales"],
                             duration_days=10, sort_order=999))
        s.add(ChangePlanTask(change_id=cid, plan="quote", name="Option gate",
                             kind="milestone", is_idea=True,
                             start_date=last.start_date + timedelta(days=140),
                             created_by=offer_world["users"]["sales"],
                             duration_days=0, sort_order=1000))
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        timing = await OfferService._quote_timing(s, change)
        snap = await OfferService._snapshot(s, change)
    # the weeks follow the committed blocks only
    assert timing["weeks_from_order"] == before["weeks_from_order"]
    ideas = {m["label"] for m in timing["milestones"] if m.get("idea")}
    assert new_ideas <= ideas <= new_ideas | seeded_ideas
    assert all(not m.get("idea") for m in timing["milestones"]
               if m["label"] not in ideas)
    snap_ideas = {t["name"] for t in snap["tasks"] if t.get("idea")}
    assert snap_ideas == new_ideas | seeded_ideas
    assert all("idea" not in t for t in snap["tasks"] if t["name"] not in snap_ideas)

    tasks = [{**t, "start": date.fromisoformat(t["start"]),
              "end": date.fromisoformat(t["end"])} for t in snap["tasks"]]
    legend = offer_pdf._kind_legend(tasks, 170 * offer_pdf.mm)
    labels = [getattr(x, "text", None) for x in legend.contents]
    assert offer_pdf.IDEA_LABEL in labels
    # a plan of one idea block still explains itself
    solo = [t for t in tasks if t["name"] == "Extra trial"]
    assert offer_pdf._kind_legend(solo, 170 * offer_pdf.mm) is not None
    # the idea bar is hatched: diagonal lines, where a committed bar has none
    from reportlab.graphics.shapes import Line
    def diagonals(ts):
        dwg = offer_pdf._plan_charts(ts, 170 * offer_pdf.mm)[0]
        return [x for x in dwg.contents if isinstance(x, Line)
                and x.x1 != x.x2 and x.y1 != x.y2]
    assert diagonals(solo)
    assert not diagonals([{**solo[0], "idea": False}])
    ctx = _pdf_ctx(tasks=tasks)
    ctx["offer"]["data"]["timing"].update(timing)
    pdf = offer_pdf.render_offer_pdf(ctx)
    assert pdf[:4] == b"%PDF"
    import io
    from pypdf import PdfReader
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Option gate (option)" in text


async def test_sent_pdf_is_frozen_and_cached_draft_is_live(
        client, offer_world, session_factory, monkeypatch):
    """A version that went out renders from its snapshot with nothing
    recomputed, once; later downloads come from the cache until the row
    changes. A draft is rendered live every time."""
    from sqlalchemy import select
    from app.models.change_plan import ChangePlanTask
    from app.services import offer_pdf, offer_service
    calls = []
    real = offer_pdf.render_offer_pdf

    def counting(ctx):
        calls.append(ctx)
        return real(ctx)
    monkeypatch.setattr(offer_pdf, "render_offer_pdf", counting)
    # the costing basis (internal cost) is not on the PDF: never computed
    async def boom(*a, **k):
        raise AssertionError("the PDF must not compute the costing basis")
    monkeypatch.setattr(offer_service.OfferService, "_costing_basis", boom)

    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    await _seed_quote_plan(client, sales, cid)
    monkeypatch.undo()
    o = await _create(client, sales, cid)
    monkeypatch.setattr(offer_pdf, "render_offer_pdf", counting)
    monkeypatch.setattr(offer_service.OfferService, "_costing_basis", boom)
    for _ in range(2):
        assert (await client.get(_url(cid, f"/{o['id']}/pdf"), headers=sales)).status_code == 200
    assert len(calls) == 2                               # drafts: live, never cached
    monkeypatch.undo()
    assert (await client.post(_url(cid, f"/{o['id']}/send"), json={},
                              headers=sales)).status_code == 200
    monkeypatch.setattr(offer_pdf, "render_offer_pdf", counting)
    monkeypatch.setattr(offer_service.OfferService, "_costing_basis", boom)
    calls.clear()
    first = (await client.get(_url(cid, f"/{o['id']}/pdf"), headers=sales)).content
    # the live plan moves on; the sent PDF does not
    async with session_factory() as s:
        t = (await s.execute(select(ChangePlanTask).where(
            ChangePlanTask.change_id == cid, ChangePlanTask.plan == "quote")
            .order_by(ChangePlanTask.id))).scalars().first()
        frozen_name = t.name
        t.name = "Renamed after sending"
        await s.commit()
    again = (await client.get(_url(cid, f"/{o['id']}/pdf"), headers=sales)).content
    assert again == first and len(calls) == 1            # served from the cache
    names = [x["name"] for x in calls[0]["tasks"]]
    assert frozen_name in names and "Renamed after sending" not in names
    # the row changes (here: its snapshot is edited): rendered afresh
    async with session_factory() as s:
        row = await s.get(ChangeOffer, o["id"])
        data = dict(row.data)
        data["_snapshot"] = {**data["_snapshot"], "plant_name": "Frozen Plant"}
        row.data = data
        await s.commit()
    await client.get(_url(cid, f"/{o['id']}/pdf"), headers=sales)
    assert len(calls) == 2 and calls[1]["plant_name"] == "Frozen Plant"


async def test_refresh_does_not_count_split_machine_time_twice(
        client, offer_world, session_factory, monkeypatch):
    """An offer built before machine time and sampling had their own lines,
    with the department's internal line overridden by Sales: the refresh
    takes the split lines out of the override and says so."""
    from app.services import offer_service
    sales = await _auth(client, "sales")
    cid = offer_world["change_id"]
    o = await _create(client, sales, cid)
    did = offer_world["depts"]["Tool Engineer"]

    def fresh_line(key, amount):
        return {"key": key, "label": key, "department": "Tool Engineer",
                "category": "internal", "amount": amount, "source_amount": amount,
                "include": True, "customer_category": "Engineering"}

    async def basis(session, change, meta=None):
        if meta is not None:
            meta.update({"currency": "EUR", "warnings": [], "versions_used": []})
        return ([fresh_line(f"dept:{did}", 2000.0), fresh_line(f"dept_mt:{did}", 600.0),
                 fresh_line(f"dept_smp:{did}", 400.0)], 3000.0)
    monkeypatch.setattr(offer_service.OfferService, "_costing_basis", basis)
    # before the split: one internal line of 3000, overridden to 5000
    async with session_factory() as s:
        row = await s.get(ChangeOffer, o["id"])
        data = dict(row.data)
        data["cost_lines"] = [{**fresh_line(f"dept:{did}", 3000.0), "amount": 5000.0,
                               "label": "Tool Engineer internal effort"}]
        row.data = data
        await s.commit()
    res = await client.post(_url(cid, f"/{o['id']}/refresh"), headers=sales)
    assert res.status_code == 200, res.text
    lines = {l["key"]: l for l in res.json()["data"]["cost_lines"]}
    assert lines[f"dept:{did}"]["amount"] == 4000.0             # 5000 - 600 - 400
    assert lines[f"dept_mt:{did}"]["amount"] == 600.0
    assert lines[f"dept_smp:{did}"]["amount"] == 400.0
    assert res.json()["totals"]["base"] == 5000.0               # not 6000
    w = {x["code"]: x for x in res.json()["warnings"]}
    assert "override_split" in w and f"'dept:{did}'" in w["override_split"]["message"]
    # a second refresh: the split lines exist now, nothing is taken twice
    res = await client.post(_url(cid, f"/{o['id']}/refresh"), headers=sales)
    lines = {l["key"]: l for l in res.json()["data"]["cost_lines"]}
    assert lines[f"dept:{did}"]["amount"] == 4000.0
    # Sales sets the amount: checked, the warning goes
    cl = list(lines.values())
    next(l for l in cl if l["key"] == f"dept:{did}")["amount"] = 3900
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {"cost_lines": cl}},
                             headers=sales)
    assert res.status_code == 200
    assert "override_split" not in {x["code"] for x in res.json()["warnings"]}
