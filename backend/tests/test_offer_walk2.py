"""Costing-to-close review fixes (after 9f089311 / d63bdf88).

Pinned here: no price reaches a non-cost viewer through the detail header,
the summation, the cost grids, the P&L or the cost report; the changelog
returns plain values; the internal offer note is blanked for non-cost
viewers; the PDF cost breakdown adds up to the printed total to the cent and
survives credit lines; a redacted bank-build save keeps the stored scrap
price; "nothing changed" sees risk details, the disclaimer and the plan and
parts on the PDF; legacy sent versions render as they were sent; a hold
resumes into its own stage only; Sales closes a rejection.
"""
import json
import shutil
import subprocess
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_offer import ChangeOffer
from app.models.entities import User
from app.services.change_service import ChangeError, ChangeService
from app.services.offer_service import (
    OfferService, SNAPSHOT_KEY, compute_totals, normalise, offer_diff, snapshot_diff,
)
from tests.test_offers import (  # noqa: F401  (offer_world is a fixture)
    _auth, _create, _sent_v1, _url, offer_world,
)

pytestmark = pytest.mark.asyncio


def _pdf_text(pdf: bytes) -> str:
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext not installed")
    return subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf,
                          capture_output=True, check=True).stdout.decode()


async def _assessments(session_factory, offer_world):
    """One assessment for Tool Engineer (the tool user's own department) and
    one for Sales, each with a cost impact."""
    async with session_factory() as s:
        own = ChangeAssessment(change_id=offer_world["change_id"],
                               department_id=offer_world["depts"]["Tool Engineer"],
                               verdict="feasible", cost_impact=4321.0)
        other = ChangeAssessment(change_id=offer_world["change_id"],
                                 department_id=offer_world["depts"]["Sales"],
                                 verdict="feasible", cost_impact=1234.0)
        s.add_all([own, other])
        await s.commit()
        return own.id, other.id


# --- 1: prices on every read path ------------------------------------------

async def test_detail_hides_negotiated_price_and_assessment_cost(
        client, offer_world, session_factory):
    cid = offer_world["change_id"]
    await _assessments(session_factory, offer_world)
    sales, tool = await _auth(client, "sales"), await _auth(client, "tool")
    await _sent_v1(client, sales, cid)
    res = await client.post(f"/api/v1/changes/{cid}/negotiations", json={
        "channel": "call", "note": "final", "counter_price": 876.5,
        "is_final": True}, headers=sales)
    assert res.status_code in (200, 201), res.text
    mine = (await client.get(f"/api/v1/changes/{cid}", headers=sales)).json()
    assert mine["negotiated_final_price"] == 876.5
    assert sorted(a["cost_impact"] for a in mine["assessments"]) == [1234.0, 4321.0]
    theirs = (await client.get(f"/api/v1/changes/{cid}", headers=tool)).json()
    assert theirs["negotiated_final_price"] is None
    assert [a["cost_impact"] for a in theirs["assessments"]] == [None, None]


async def test_summation_and_actuals_are_cost_roles_only(client, offer_world):
    cid = offer_world["change_id"]
    sales, tool = await _auth(client, "sales"), await _auth(client, "tool")
    for path in (f"/api/v1/changes/{cid}/summation",
                 f"/api/v1/pnl/changes/{cid}/actuals"):
        assert (await client.get(path, headers=tool)).status_code == 403, path
        res = await client.get(path, headers=sales)
        assert res.status_code == 200, (path, res.text)


async def test_cost_lines_own_department_only_for_non_cost_roles(
        client, offer_world, session_factory):
    cid = offer_world["change_id"]
    own, other = await _assessments(session_factory, offer_world)
    sales, tool = await _auth(client, "sales"), await _auth(client, "tool")
    url = f"/api/v1/changes/{cid}/assessments/{{}}/cost-lines"
    assert (await client.get(url.format(own), headers=tool)).status_code == 200
    assert (await client.get(url.format(other), headers=tool)).status_code == 403
    for aid in (own, other):
        assert (await client.get(url.format(aid), headers=sales)).status_code == 200


async def test_portfolio_money_only_for_changes_the_viewer_may_price(
        client, offer_world, session_factory):
    cid = offer_world["change_id"]
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        change.quoted_price = 999.0
        change.estimated_cost = 555.0
        await s.commit()
    sales, tool = await _auth(client, "sales"), await _auth(client, "tool")

    def ids(body):
        return {r["change_id"] for r in body["rows"]}
    assert cid in ids((await client.get("/api/v1/pnl/changes", headers=sales)).json())
    assert cid not in ids((await client.get("/api/v1/pnl/changes", headers=tool)).json())
    assert (await client.get("/api/v1/pnl/summary", headers=sales)).json()["count"] >= 1
    tool_sum = (await client.get("/api/v1/pnl/summary", headers=tool)).json()
    assert tool_sum["count"] == 0 and tool_sum["totals"]["revenue"] == 0
    rc_sales = (await client.get("/api/v1/reports/cost", headers=sales)).json()
    assert any(p["budget"] == 555.0 for p in rc_sales["projects"])
    rc_tool = (await client.get("/api/v1/reports/cost", headers=tool)).json()
    assert not any(p["budget"] for p in rc_tool["projects"])
    # the change lead reads the money of the change they lead
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        change.lead_id = offer_world["users"]["tool"]
        await s.commit()
    assert cid in ids((await client.get("/api/v1/pnl/changes", headers=tool)).json())
    rc_lead = (await client.get("/api/v1/reports/cost", headers=tool)).json()
    assert any(p["budget"] == 555.0 for p in rc_lead["projects"])


# --- 2 / 3: changelog values ------------------------------------------------

async def test_changelog_values_are_plain_and_offer_note_is_internal(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    sales, tool = await _auth(client, "sales"), await _auth(client, "tool")
    o = await _create(client, sales, cid)
    await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "timing": {"include": False}}}, headers=sales)
    res = await client.post(_url(cid, f"/{o['id']}/send"),
                            json={"change_note": "margin cut to 3% (was 8%)"}, headers=sales)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "on_hold", seed["admin_id"])
        await s.commit()
    for auth in (sales, tool):
        log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=auth)).json()
        hold = [e for e in log if e["field_name"] == "status"
                and e["new_value"] == "on_hold"]
        assert [e["old_value"] for e in hold] == ["quoted"]
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=tool)).json()
    sent = next(e for e in log if e["action"] == "offer_sent")
    assert "margin" not in json.dumps(sent)
    assert json.loads(sent["new_value"])["note"] is None
    audit = (await client.get("/api/v1/audit?correlation_id=C-O-1", headers=tool)).json()
    assert "margin cut" not in json.dumps(audit)
    audit_sales = (await client.get("/api/v1/audit?correlation_id=C-O-1",
                                    headers=sales)).json()
    assert "margin cut" in json.dumps(audit_sales)


async def test_offer_override_reason_is_redacted():
    from app.services.price_redaction import redact_changelog_text, redact_value
    v = {"offer_id": 1, "expired": True, "expired_override_reason": "gave 5% off"}
    assert redact_value(v, "offer_accepted")["expired_override_reason"] is None
    # only offer_* actions: a 'note' elsewhere is not an offer note
    assert redact_value({"note": "x"}, "bank_build_decided") == {"note": "x"}
    desc, notes = redact_changelog_text(
        "offer_accepted", "Offer v2 accepted by the customer after expiry (gave 5% off)",
        "gave 5% off")
    assert "5%" not in desc and notes is None


# --- 4 / 5: the PDF cost breakdown ------------------------------------------

def _amounts(text: str, start: str, end: str) -> dict:
    """Label -> amount for the rows of the price table (German format)."""
    out = {}
    block = text[text.index(start):text.index(end) + 200]
    for line in block.splitlines():
        parts = line.rsplit(None, 2)
        if len(parts) == 3 and parts[2] == "EUR":
            try:
                out[parts[0].strip()] = float(parts[1].replace(".", "").replace(",", "."))
            except ValueError:
                pass
    return out


async def test_pdf_breakdown_adds_up_to_the_printed_total():
    from app.services.offer_pdf import render_offer_pdf
    from tests.test_offer_walk1 import _pdf_ctx
    data = {"cost_lines": [{"key": "a", "label": "Tooling", "amount": 100.2}],
            "factors": [{"key": "engineering_fee", "label": "Engineering fee",
                         "type": "amount", "value": 10.005, "enabled": True}],
            "risks": [{"concern_id": 1, "type": "pct", "value": 2.5}],
            "free_fields": [{"label": "Freight", "amount": 0.335}],
            "changeover": {"mode": "customer_pays_scrap", "scrap_qty": 3,
                           "scrap_unit_price": 0.335},
            "timing": {"include": False}}
    ctx = _pdf_ctx(data)
    total = ctx["offer"]["totals"]["total_one_time"]
    rows = _amounts(_pdf_text(render_offer_pdf(ctx)), "Cost breakdown", "Total one-time")
    printed = {k: v for k, v in rows.items() if not k.startswith(("Cost basis", "Total"))}
    assert round(sum(printed.values()), 2) == total


async def test_spread_ignores_credit_lines_and_needs_a_positive_one():
    from app.services.offer_pdf import EXTRA_CBD_LABEL, spread_cbd
    rows = spread_cbd([{"label": "A", "amount": 1000}, {"label": "Credit", "amount": -999}],
                      200)
    assert rows == [("A", 1200), ("Credit", -999)]
    rows = spread_cbd([{"label": "Credit", "amount": -50}], 200)
    assert rows == [("Credit", -50), (EXTRA_CBD_LABEL, 200)]
    # the target wins over sum + hidden: the last positive line absorbs it
    rows = spread_cbd([{"label": "A", "amount": 10}, {"label": "B", "amount": 20},
                       {"label": "C", "amount": -5}], 3, target=28.01)
    assert round(sum(a for _, a in rows), 2) == 28.01 and rows[2] == ("C", -5)


# --- 6: bank build with a redacted price ------------------------------------

async def test_bank_build_keeps_the_stored_price_when_omitted(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        admin = await s.get(User, seed["admin_id"])
        change.status = "approved"
        await ChangeService.set_bank_build(s, change, "planned_scrap", admin,
                                           scrap_quote_price=500)
        await ChangeService.set_bank_build(s, change, "planned_scrap", admin,
                                           note="re-decided")
        assert change.scrap_quote_price == 500
        await ChangeService.set_bank_build(s, change, "running_change", admin)
        with pytest.raises(ChangeError, match="scrap quote"):
            await ChangeService.set_bank_build(s, change, "planned_scrap", admin)
        await ChangeService.set_bank_build(s, change, "planned_scrap", admin,
                                           scrap_quote_price=450)
        await s.commit()
    tool = await _auth(client, "tool")
    theirs = (await client.get(f"/api/v1/changes/{cid}", headers=tool)).json()
    assert theirs["scrap_quote_price"] is None and theirs["scrap_price_set"] is True


# --- 7: "nothing changed" ---------------------------------------------------

async def test_diff_sees_risk_details_and_the_disclaimer():
    prev = normalise({"cost_lines": [{"key": "a", "amount": 10}],
                      "risks": [{"concern_id": 1, "label": "Fill", "severity": 2,
                                 "department": "Tool", "note": "rib end", "value": 0}],
                      "timing": {"disclaimer": "Draft timing."}})
    cur = json.loads(json.dumps(prev))
    t = compute_totals(prev, 0)
    assert offer_diff(prev, t, cur, t) == []
    cur["risks"][0].update(note="rib end and boss", severity=3,
                           department="Tool Shop", label="Filling")
    cur["timing"]["disclaimer"] = "Final timing after order."
    fields = {d["field"] for d in offer_diff(prev, t, cur, t)}
    assert {"Risk 1 label", "Risk Filling severity", "Risk Filling department",
            "Risk Filling note", "Timing disclaimer"} <= fields


async def test_snapshot_diff_sees_the_plan_and_the_parts():
    snap = {"tasks": [{"name": "Tool", "start": "2026-10-01", "duration": 5, "end": "x"}],
            "items": [{"number": "P1", "name": "Bracket", "index": "B"}],
            "taken_at": "then"}
    same = {**snap, "taken_at": "now"}
    assert snapshot_diff(snap, same) == []
    assert snapshot_diff(None, same) == []
    moved = {**snap, "tasks": [{**snap["tasks"][0], "start": "2026-10-08"}]}
    assert [d["field"] for d in snapshot_diff(snap, moved)] == ["Quote plan"]
    reindexed = {**snap, "items": [{**snap["items"][0], "index": "C"}]}
    assert [d["field"] for d in snapshot_diff(snap, reindexed)] == ["Impacted parts"]


async def test_resend_allowed_when_only_the_parts_changed(
        client, offer_world, session_factory):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    v1 = await _sent_v1(client, sales, cid)
    async with session_factory() as s:
        row = await s.get(ChangeOffer, v1["id"])
        data = dict(row.data)
        data[SNAPSHOT_KEY] = {**data[SNAPSHOT_KEY], "items": [
            {"number": "OLD-1", "name": "Old part", "index": "A"}]}
        row.data = data
        await s.commit()
    v2 = await _create(client, sales, cid)
    await client.patch(_url(cid, f"/{v2['id']}"), json={
        "data": {"timing": {"include": False}}, "change_note": "parts"},
        headers=sales)
    res = await client.post(_url(cid, f"/{v2['id']}/send"), json={"change_note": "parts"},
                            headers=sales)
    assert res.status_code == 200, res.text


# --- 9: legacy sent versions -------------------------------------------------

async def test_legacy_sent_offer_renders_as_it_was_sent(
        client, offer_world, session_factory):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    v1 = await _sent_v1(client, sales, cid)
    async with session_factory() as s:
        row = await s.get(ChangeOffer, v1["id"])
        data = {k: v for k, v in row.data.items()
                if k not in (SNAPSHOT_KEY, "scope_text", "show_risk_surcharge")}
        data["factors"] = [{k: v for k, v in f.items() if k != "show"}
                           for f in data["factors"]]
        for f in data["factors"]:
            if f["key"] == "overhead":
                f.update(enabled=True, value=10)
        row.data = data
        await s.commit()
        change = await ChangeService.get_change(s, cid)
        offer = (await s.execute(select(ChangeOffer).where(
            ChangeOffer.id == v1["id"]))).scalar_one()
        text = _pdf_text(await OfferService.pdf_bytes(s, change, offer))
    assert "Overhead" in text
    assert "Rib +0.5 mm" in text


# --- 10: resume into the pre-hold stage -------------------------------------

async def test_resume_must_return_to_the_pre_hold_status(session_factory,
                                                         offer_world, seed):
    cid = offer_world["change_id"]
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        change.status = "captured"
        await s.flush()
        await ChangeService.transition(s, change, "on_hold", seed["admin_id"])
        with pytest.raises(ChangeError, match="'captured'"):
            await ChangeService.transition(s, change, "scoping", seed["admin_id"])
        await ChangeService.transition(s, change, "captured", seed["admin_id"])
        assert change.status == "captured"
        await ChangeService.transition(s, change, "on_hold", seed["admin_id"])
        await ChangeService.transition(s, change, "cancelled", seed["admin_id"],
                                       cancellation_reason="dropped")
        assert change.status == "cancelled"


# --- 11: closing a rejection -------------------------------------------------

async def test_sales_closes_a_rejected_change(client, offer_world, session_factory):
    cid = offer_world["change_id"]
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        change.status = "rejected"
        change.customer_relevant = False
        change.rejected_at = datetime.utcnow()
        await s.commit()
    tool, sales = await _auth(client, "tool"), await _auth(client, "sales")
    url = f"/api/v1/changes/{cid}/transition"
    assert (await client.post(url, json={"to_status": "closed"},
                              headers=tool)).status_code == 403
    res = await client.post(url, json={"to_status": "closed"}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "closed"


async def test_sales_does_not_close_a_released_change(client, offer_world,
                                                      session_factory):
    cid = offer_world["change_id"]
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        change.status = "released"
        await s.commit()
    sales = await _auth(client, "sales")
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "closed"}, headers=sales)
    assert res.status_code == 403
