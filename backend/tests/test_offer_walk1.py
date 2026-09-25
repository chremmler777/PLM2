"""Offer fixes from live walk 1 and its review.

Pinned here: the receipt date bounds; an accepted offer has no clock and
decides the bank build; the diff lists everything the customer would see
and an unchanged version cannot be sent; a draft can be discarded; factors
carry a `show` flag and hidden money is folded into the cost lines on the
PDF (sum unchanged); numbers print in the currency's locale; the recipient
warning; the number reading rule shared with the Offer tab; a PATCH is
strict only for what it sends; the send snapshot; customer_note vs the
internal change_note; prices redacted for non-cost viewers; an accepted
answer is final; a hold resumes into the stage it was taken from.
"""
import csv
import io
import json
import shutil
import subprocess
from datetime import date, datetime, timedelta

import pytest

from app.models.change import ChangeRequest
from app.models.change_offer import ChangeOffer
from app.services.change_service import ChangeError, ChangeService
from app.services.offer_service import OfferService, compute_totals, normalise
from tests.test_offers import (  # noqa: F401  (offer_world is a fixture)
    _auth, _create, _sent_v1, _url, offer_world,
)

pytestmark = pytest.mark.asyncio


def _pdf_text(pdf: bytes) -> str:
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext not installed")
    return subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf,
                          capture_output=True, check=True).stdout.decode()


async def _accept(client, auth, cid, **extra):
    due = (datetime.utcnow() + timedelta(days=90)).isoformat()
    return await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": due, **extra}, headers=auth)


# --- B2 / review 6: receipt date --------------------------------------------

async def test_receipt_date_bounds():
    today = datetime.utcnow().date()
    OfferService._check_received(today + timedelta(days=1))     # local day ahead of UTC
    OfferService._check_received(today - timedelta(days=30))    # recorded after the fact
    with pytest.raises(ChangeError, match="future"):
        OfferService._check_received(today + timedelta(days=2))
    with pytest.raises(ChangeError, match="60 days ago"):
        OfferService._check_received(today - timedelta(days=61))


# --- B4 / B8 / review 5: acceptance -----------------------------------------

async def test_acceptance_stops_the_clock_decides_the_bank_build_and_is_final(
        client, offer_world, session_factory):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "timing": {"include": False},
        "changeover": {"mode": "customer_pays_scrap", "scrap_qty": 10,
                       "scrap_unit_price": "2,5"}}}, headers=sales)
    assert (await client.post(_url(cid, f"/{o['id']}/send"), json={},
                              headers=sales)).status_code == 200
    res = await _accept(client, sales, cid)
    assert res.status_code == 200, res.text
    got = (await client.get(_url(cid), headers=sales)).json()[0]
    assert got["status"] == "accepted"
    assert got["days_left"] is None and got["expired"] is False
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.bank_build_mode == "planned_scrap"
        assert float(change.scrap_quote_price) == 25.0
        assert change.bank_build_set_at is not None
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=sales)).json()
    bb = next(e for e in log if e["action"] == "bank_build_decided")
    assert "from the accepted offer v1" in bb["action_description"]
    # the answer is final
    res = await client.post(f"/api/v1/changes/{cid}/customer-response",
                            json={"response": "declined"}, headers=sales)
    assert res.status_code == 400
    assert res.json()["detail"].startswith("The customer accepted v1;")


async def test_acceptance_keeps_a_bank_build_already_decided(
        client, offer_world, session_factory):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    await _sent_v1(client, sales, cid)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        change.bank_build_mode = "planned_scrap"
        change.scrap_quote_price = 99.0
        await s.commit()
    assert (await _accept(client, sales, cid)).status_code == 200
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.bank_build_mode == "planned_scrap"
        assert float(change.scrap_quote_price) == 99.0


async def test_running_change_offer_sets_running_change(client, offer_world,
                                                        session_factory):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    await _sent_v1(client, sales, cid)
    assert (await _accept(client, sales, cid)).status_code == 200
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert change.bank_build_mode == "running_change"
        assert change.scrap_quote_price is None


# --- B6: diff and the unchanged version --------------------------------------

async def test_diff_covers_everything_and_an_unchanged_version_is_refused(
        client, offer_world):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    await _sent_v1(client, sales, cid)
    v2 = await _create(client, sales, cid)
    res = await client.post(_url(cid, f"/{v2['id']}/send"),
                            json={"change_note": "same again"}, headers=sales)
    assert res.status_code == 400
    assert res.json()["detail"] == "Nothing changed since v1; change the offer or keep v1"
    d = v2["data"]
    lines = d["cost_lines"] + [{"key": "manual", "label": "Handling",
                                "category": "other", "amount": 40, "include": True}]
    factors = d["factors"] + [{"key": "tooling_fee", "label": "Tooling fee",
                               "type": "amount", "value": 0, "enabled": False}]
    res = await client.patch(_url(cid, f"/{v2['id']}"), json={"data": {
        "cost_lines": lines, "factors": factors,
        "free_fields": [{"label": "Transport", "amount": 30}],
        "changeover": {"note": "bank of 2 weeks"},
        "piece_price": {"enabled": True, "rows": [{"label": "Material",
                                                   "delta_per_piece": 0.01}]},
        "customer_note": "Handling and transport added",
        "show_risk_surcharge": True,
    }}, headers=sales)
    assert res.status_code == 200, res.text
    fields = {x["field"] for x in res.json()["diff"]}
    for f in ("Cost line Handling added", "Factor Tooling fee added",
              "Free field Transport added", "Changeover note",
              "Piece price effect", "Piece price Material",
              "Note to the customer", "Risk surcharges shown on offer"):
        assert f in fields, (f, fields)
    res = await client.post(_url(cid, f"/{v2['id']}/send"),
                            json={"change_note": "handling"}, headers=sales)
    assert res.status_code == 200, res.text


# --- B7: discard a draft ----------------------------------------------------

async def test_discard_draft(client, offer_world):
    cid = offer_world["change_id"]
    sales, tool = await _auth(client, "sales"), await _auth(client, "tool")
    v1 = await _sent_v1(client, sales, cid)
    assert (await client.delete(_url(cid, f"/{v1['id']}"),
                                headers=sales)).status_code == 400   # sent
    v2 = await _create(client, sales, cid)
    assert (await client.delete(_url(cid, f"/{v2['id']}"),
                                headers=tool)).status_code == 403
    res = await client.delete(_url(cid, f"/{v2['id']}"), headers=sales)
    assert res.status_code == 204
    assert [o["version"] for o in (await client.get(_url(cid), headers=sales)).json()] == [1]
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=sales)).json()
    assert any(e["action"] == "offer_draft_discarded"
               and e["action_description"] == "Draft offer v2 discarded" for e in log)
    assert (await _create(client, sales, cid))["version"] == 2


# --- B9: show flags ----------------------------------------------------------

async def test_show_flags_default_and_totals_unchanged():
    d = normalise({"factors": [
        {"key": "overhead", "value": 10, "enabled": True},
        {"key": "margin", "value": 10, "enabled": True},
        {"key": "engineering_fee", "type": "amount", "value": 100, "enabled": True},
        {"key": "custom_x", "type": "amount", "value": 5, "enabled": True},
        {"key": "margin2", "value": 1, "enabled": True, "show": "false"},
    ], "cost_lines": [{"key": "a", "amount": 1000}]})
    shows = {f["key"]: f["show"] for f in d["factors"]}
    assert shows == {"overhead": False, "margin": False, "engineering_fee": True,
                     "custom_x": True, "margin2": False}
    assert d["show_risk_surcharge"] is False
    assert compute_totals(d, 0)["total_one_time"] == 1000 + 100 + 100 + 100 + 5 + 10


async def test_spread_cbd_keeps_the_sum_to_the_cent():
    from app.services.offer_pdf import spread_cbd
    lines = [{"amount": 100}, {"amount": 200}, {"amount": 33.33}]
    out = [a for _, a in spread_cbd(lines, 10.01)]
    assert round(sum(out), 2) == round(333.33 + 10.01, 2)
    assert out[0] < out[1] and out[0] > 100
    assert [a for _, a in spread_cbd(lines, 0)] == [100, 200, 33.33]
    # No positive line to carry it: the hidden amount is its own row.
    assert spread_cbd([{"amount": 0, "label": "A"}, {"amount": 0, "label": "B"}], 1) \
        == [("A", 0), ("B", 0), ("Engineering and handling", 1)]
    assert spread_cbd([], 5) == [("Engineering and handling", 5)]
    assert spread_cbd([], 0) == []


def _pdf_ctx(data, *, status="sent", currency="EUR", change_note=None):
    d = normalise(data)
    return {
        "org_name": "Org", "plant_name": "Plant Wolfsburg",
        "plant_location": "Wolfsburg", "project_name": "P",
        "change_number": "C-W-1", "title": "T", "items": [],
        "offer": {"version": 2, "status": status, "currency": currency,
                  "data": d, "totals": compute_totals(d, 0),
                  "change_note": change_note, "sent_at": date.today(),
                  "valid_until": date.today() + timedelta(days=30)},
        "tasks": [],
    }


async def test_pdf_folds_hidden_money_into_the_lines():
    from app.services.offer_pdf import render_offer_pdf
    data = {"cost_lines": [{"key": "a", "label": "Tooling", "amount": 1000},
                           {"key": "b", "label": "Sampling", "amount": 3000}],
            "factors": [{"key": "overhead", "label": "Overhead", "value": 10,
                         "enabled": True},
                        {"key": "engineering_fee", "label": "Engineering fee",
                         "type": "amount", "value": 250, "enabled": True}],
            "risks": [{"concern_id": 1, "label": "Fill", "value": 5, "show": True,
                       "severity": 2}],
            "timing": {"include": False}}
    text = _pdf_text(render_offer_pdf(_pdf_ctx(data)))
    # 10% overhead (400) + 5% risk (200) spread 1:3 over the two lines
    assert "1.150,00 EUR" in text and "3.450,00 EUR" in text
    assert "Overhead" not in text and "Risk surcharges" not in text
    assert "Engineering fee" in text and "4.850,00 EUR" in text
    assert "Internal" not in text and "External" not in text    # no category column
    data["show_risk_surcharge"] = True
    text = _pdf_text(render_offer_pdf(_pdf_ctx(data)))
    assert "Risk surcharges" in text and "1.100,00 EUR" in text


# --- B10: formatting, letterhead, recipient ----------------------------------

async def test_number_format_follows_the_currency_and_plant_line():
    from app.services.offer_pdf import _money, _piece, plant_line
    assert _money(1234.5, "EUR") == "1.234,50 EUR"
    assert _money(1234.5, "CHF") == "1.234,50 CHF"
    assert _money(1234.5, "USD") == "1,234.50 USD"
    assert _money(-1234.5, "GBP") == "-1,234.50 GBP"
    assert _piece(0.0125, "USD") == "+0.0125 USD"
    assert plant_line("Plant Wolfsburg", "Wolfsburg") == "Plant Wolfsburg"
    assert plant_line("Plant 2", "Wolfsburg") == "Plant 2, Wolfsburg"
    assert plant_line("", "Wolfsburg") == "Wolfsburg"


async def test_pdf_usd_letterhead_and_notes():
    from app.services.offer_pdf import render_offer_pdf
    ctx = _pdf_ctx({"cost_lines": [{"key": "a", "label": "Tooling", "amount": 1234.5}],
                    "timing": {"include": False},
                    "customer_note": "Discount of 3% agreed on the call"},
                   currency="USD", change_note="INTERNAL margin talk")
    text = _pdf_text(render_offer_pdf(ctx))
    assert "1,234.50 USD" in text
    assert "Plant Wolfsburg, Wolfsburg" not in text and "Plant Wolfsburg" in text
    assert "Discount of 3% agreed on the call" in text
    assert "INTERNAL margin talk" not in text


async def test_recipient_missing_warning(client, offer_world):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    assert "recipient_missing" in {w["code"] for w in o["warnings"]}
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "recipient": {"company": "ACME Automotive"}}}, headers=sales)
    assert "recipient_missing" not in {w["code"] for w in res.json()["warnings"]}


# --- review 4: number reading, same vectors as offerFormat.test.ts -----------

NUMBER_VECTORS = [
    ("1.234", 1234), ("12.345.678", 12345678), ("1.234,5", 1234.5), ("1,5", 1.5),
    ("1.5", 1.5), ("1.23", 1.23), ("-2.000", -2000), ("1 234,50", 1234.5),
    ("1,", 1), ("", None), ("abc", None), ("1.23.4", None), ("1.23,4", None),
    ("1,2,3", None), ("0.125", 0.125), ("-0.125", -0.125), ("0.500", 0.5),
    ("1.2345", 1.2345), ("1.234,56", 1234.56), ("0.125,5", None),
    # backend extras: en-US with both separators, and junk
    ("1,234.50", 1234.5), ("1_000", None), ("12,34.5", None),
    # Swiss apostrophe grouping is refused, as on the frontend
    ("1'234", None), ("1'234,50", None),
]


@pytest.mark.parametrize("text,expected", NUMBER_VECTORS)
async def test_read_number_vectors(text, expected):
    from app.services.offer_service import read_number
    assert read_number(text) == expected


# --- review 11 / 4: strict only for what the PATCH sends ---------------------

async def test_patch_is_strict_only_for_its_keys(client, offer_world, session_factory):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    async with session_factory() as s:
        row = await s.get(ChangeOffer, o["id"])
        data = dict(row.data)
        data["cost_lines"] = data["cost_lines"] + [
            {"key": "legacy", "label": "Legacy", "amount": "1_000", "include": True}]
        data["cbd_mode"] = "fancy"
        row.data = data
        await s.commit()
    got = (await client.get(_url(cid), headers=sales)).json()[0]
    w = {x["code"]: x for x in got["warnings"]}
    assert "number_unreadable" in w and "Legacy" in w["number_unreadable"]["message"]
    assert got["totals"]["base"] == 1000         # the unreadable line is left out
    line = next(l for l in got["data"]["cost_lines"] if l["key"] == "legacy")
    assert line["amount"] is None
    # an unrelated edit goes through; a bad value in the edit itself does not
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {"intro": "Hello"}},
                             headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["cbd_mode"] == "detailed"
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {"cbd_mode": "fancy"}},
                             headers=sales)
    assert res.status_code == 400
    # the snapshot is server-owned
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "_snapshot": {"org_name": "Forged"}}}, headers=sales)
    assert res.status_code == 200
    async with session_factory() as s:
        assert "_snapshot" not in (await s.get(ChangeOffer, o["id"])).data


# --- review 9: snapshot and watermark ----------------------------------------

async def test_sent_version_renders_from_its_snapshot(client, offer_world,
                                                      session_factory):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    v1 = await _sent_v1(client, sales, cid)
    assert "_snapshot" not in v1["data"]
    async with session_factory() as s:
        row = await s.get(ChangeOffer, v1["id"])
        snap = row.data["_snapshot"]
        assert snap["change_number"] == "C-O-1" and "tasks" in snap
        data = dict(row.data)
        # "Issued by" prints the profile's legal name (final walk P2-7), so
        # the snapshot is proven through the plant it froze instead.
        data["_snapshot"] = {**snap, "plant_name": "Snapshot Plant Dallas"}
        row.data = data
        await s.commit()
    pdf = (await client.get(_url(cid, f"/{v1['id']}/pdf"), headers=sales)).content
    assert "Snapshot Plant Dallas" in _pdf_text(pdf)
    v2 = await _create(client, sales, cid)
    assert "_snapshot" not in v2["data"]
    await client.patch(_url(cid, f"/{v2['id']}"), json={"data": {"intro": "v2"}},
                       headers=sales)
    assert (await client.post(_url(cid, f"/{v2['id']}/send"),
                              json={"change_note": "intro"}, headers=sales)).status_code == 200
    pdf = (await client.get(_url(cid, f"/{v1['id']}/pdf"), headers=sales)).content
    assert "SUPERSEDED" in _pdf_text(pdf)


async def test_pdf_scope_uses_scope_text_not_the_internal_description():
    from app.services.offer_pdf import render_offer_pdf
    ctx = _pdf_ctx({"scope_text": "Rib reinforced by 0.5 mm.", "timing": {"include": False}})
    ctx["reason"], ctx["description"] = "internal reason", "internal description"
    text = _pdf_text(render_offer_pdf(ctx))
    assert "Rib reinforced by 0.5 mm." in text
    assert "internal reason" not in text and "internal description" not in text


async def test_pdf_long_unbroken_strings_stay_on_the_page():
    from app.services.offer_pdf import fit_text, render_offer_pdf
    from reportlab.pdfbase.pdfmetrics import stringWidth
    long = "X" * 400
    ctx = _pdf_ctx({"cost_lines": [{"key": "a", "label": long, "amount": 1}],
                    "scope_text": long, "timing": {"include": True}})
    ctx["org_name"] = "O" * 300
    ctx["tasks"] = [{"name": long, "lane": "L", "start": date(2026, 10, 1),
                     "end": date(2026, 10, 9), "duration": 8}]
    assert render_offer_pdf(ctx)[:4] == b"%PDF"
    cut = fit_text(long, "Helvetica", 7.5, 100)
    assert cut.endswith("...") and stringWidth(cut, "Helvetica", 7.5) <= 100


# --- review 1 / 2: prices for non-cost viewers -------------------------------

async def test_prices_are_redacted_for_non_cost_viewers(client, offer_world,
                                                        session_factory):
    cid = offer_world["change_id"]
    sales, tool = await _auth(client, "sales"), await _auth(client, "tool")
    o = await _create(client, sales, cid)
    await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "timing": {"include": False}}}, headers=sales)
    await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    await client.post(f"/api/v1/changes/{cid}/negotiations", json={
        "channel": "call", "note": "they want less", "counter_price": 876.5},
        headers=sales)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.append_changelog(
            s, change, "bank_build_decided",
            "Bank build decided: planned scrap (scrap quote 555)", 1,
            new_value={"mode": "planned_scrap", "scrap_quote_price": 555.0})
        await ChangeService.append_changelog(
            s, change, "offer_sent", "Offer v9 sent, valid until 2026-10-30 "
            "(margin cut to 3%)", 1, notes="margin cut to 3%")
        await s.commit()

    mine = (await client.get(f"/api/v1/changes/{cid}", headers=sales)).json()
    assert mine["quoted_price"] == 1000
    theirs = (await client.get(f"/api/v1/changes/{cid}", headers=tool)).json()
    assert theirs["quoted_price"] is None and theirs["scrap_quote_price"] is None
    listed = next(c for c in (await client.get("/api/v1/changes", headers=tool)).json()
                  if c["id"] == cid)
    assert listed["quoted_price"] is None

    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=tool)).json()
    text = " ".join(f"{e['action_description']} {e['notes'] or ''}" for e in log)
    assert "555" not in text and "margin cut" not in text

    audit = (await client.get(f"/api/v1/audit?correlation_id=C-O-1",
                              headers=tool)).json()
    blob = json.dumps(audit)
    assert "876.5" not in blob and "555" not in blob
    assert any(r["action"] == "negotiation_round"
               and json.loads(r["new_values"])["counter_price"] is None for r in audit)
    csv_text = (await client.get("/api/v1/audit/export?correlation_id=C-O-1",
                                 headers=tool)).text
    # Only the value columns: the hash columns are random hex and may hold
    # "555" by chance.
    values = " ".join(f"{r['old_values']} {r['new_values']}"
                      for r in csv.DictReader(io.StringIO(csv_text)))
    assert "counter_price" in values                 # the rows are there
    assert "876.5" not in values and "555" not in values
    audit_sales = json.dumps((await client.get(
        "/api/v1/audit?correlation_id=C-O-1", headers=sales)).json())
    assert "876.5" in audit_sales


# --- review 3: a hold resumes into the stage it came from --------------------

async def test_hold_resumes_into_its_own_stage(session_factory, offer_world, seed):
    cid = offer_world["change_id"]
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        change.status = "approved"
        change.impact_confirmed_at = datetime.utcnow()
        await s.flush()
        await ChangeService.transition(s, change, "on_hold", seed["admin_id"])
        with pytest.raises(ChangeError, match="Resume to the stage the change was in"):
            await ChangeService.transition(s, change, "in_implementation",
                                           seed["admin_id"])
        # a hold taken during implementation resumes there
        change.status = "in_implementation"
        await s.flush()
        await ChangeService.transition(s, change, "on_hold", seed["admin_id"])
        before = await ChangeService._status_before_hold(s, change)
        assert before == "in_implementation"
