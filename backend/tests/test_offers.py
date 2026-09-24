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
    assert d["recipient"]["company"] == "Project"
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
        ("Fill issue", 3, True, 0)
    assert d["changeover"]["mode"] == "running_change"
    assert d["timing"]["include"] is True
    assert d["timing"]["weeks_from_order"] >= 1
    assert "Start of production (change)" in [m["label"] for m in d["timing"]["milestones"]]
    assert d["terms"]["payment"] == "30 days net"
    assert o["totals"]["base"] == 1000 and o["totals"]["internal_cost"] == 1000
    assert o["diff"] is None
    assert "high_risk_unpriced" in {w["code"] for w in o["warnings"]}


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
    res = await client.post(_url(cid, f"/{o['id']}/send"),
                            json={"received_at": "2026-10-01"}, headers=sales)
    assert res.status_code == 200, res.text
    v1 = res.json()
    assert v1["status"] == "sent" and v1["received_at"] == "2026-10-01"
    assert v1["valid_until"] == "2026-10-31"
    assert v1["sent_by_name"] == "Offer sales"
    change = (await client.get(f"/api/v1/changes/{cid}", headers=sales)).json()
    assert change["status"] == "quoted"
    assert change["quoted_price"] == 1000
    # a sent version is frozen
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {}}, headers=sales)
    assert res.status_code == 400

    # receipt date corrected: validity recomputed
    res = await client.post(_url(cid, f"/{o['id']}/received"),
                            json={"received_at": "2026-10-05"}, headers=sales)
    assert res.status_code == 200 and res.json()["valid_until"] == "2026-11-04"

    v2 = await _create(client, sales, cid)
    assert v2["version"] == 2 and v2["data"]["subject"] == v1["data"]["subject"]
    res = await client.post(_url(cid, f"/{v2['id']}/received"),
                            json={"received_at": "2026-10-05"}, headers=sales)
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
        row.valid_until = date.today() - timedelta(days=1)
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
