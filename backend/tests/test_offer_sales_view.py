"""Christoph 2026-11-09: Sales sees all risks and decides, writes his own
risks and notes, picks the cost blocks and supplier quotes, puts a
multiplier / overhead on top that never shows in the customer CBD, sees the
margin per department, and finishes with one ZIP of everything (offer PDF,
internal breakdown, supplier quote files); PM is told who offered when."""
import io
import os
import tempfile
import zipfile

import pytest
from sqlalchemy import select

from app.models.change import ChangeAttachment, ChangeConcern
from app.models.change_cost import CostingOffer
from app.models.notification import Notification
from app.services.offer_service import compute_totals, normalise
from tests.test_offers import (  # noqa: F401  (fixture)
    _auth, _create, _seed_quote_plan, _url, offer_world,
)

pytestmark = pytest.mark.asyncio


async def test_all_risks_own_risks_and_notes(client, offer_world, session_factory):
    cid = offer_world["change_id"]
    async with session_factory() as s:
        s.add(ChangeConcern(change_id=cid, kind="needs_info", flag_type="question",
                            note="Wall thickness at boss", answer_kind="assumed",
                            assumed_value="2.5", assumed_unit="mm",
                            assumed_risk="re-cut if thinner",
                            department_id=offer_world["depts"]["Tool Engineer"],
                            raised_by=offer_world["users"]["tool"]))
        await s.commit()
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    by_src = {}
    for r in o["data"]["risks"]:
        by_src.setdefault(r["source"], []).append(r)
    # register risk, the open assumption and the estimate-priced position
    assert {"risk", "assumption", "estimate"} <= set(by_src)
    assert by_src["assumption"][0]["label"].startswith("Assumed: Wall thickness")
    assert by_src["assumption"][0]["note"] == "re-cut if thinner"
    risks = o["data"]["risks"] + [{
        "key": "own:1", "source": "sales", "concern_id": None,
        "label": "Customer resin not yet released", "show": True,
        "type": "amount", "value": 250, "note": "price holds for released grade"}]
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "risks": risks, "other_notes": "Prices exclude PPAP level 3."}}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["totals"]["risks_total"] == 250
    # a refresh keeps Sales' own risk and the decision on the register rows
    res = await client.post(_url(cid, f"/{o['id']}/refresh"), headers=sales)
    d = res.json()["data"]
    assert any(r["key"] == "own:1" and r["value"] == 250 for r in d["risks"])
    assert d["other_notes"] == "Prices exclude PPAP level 3."
    # an own risk still without text saves (autosave while typing)
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {"risks": d["risks"] + [
        {"key": "own:2", "source": "sales", "label": "", "show": True,
         "type": "amount", "value": 0}]}}, headers=sales)
    assert res.status_code == 200, res.text


async def test_multiplier_is_folded_never_shown_and_margin_per_department():
    data = normalise({"cost_lines": [
        {"key": "a", "label": "Tool", "department": "Tool Engineer", "amount": 1000,
         "include": True, "customer_category": "Tooling"},
        {"key": "b", "label": "Design", "department": "Design", "amount": 500,
         "include": True, "customer_category": "Engineering"},
        {"key": "c", "label": "Dropped", "department": "Design", "amount": 300,
         "include": False}],
        "factors": [
            {"key": "sales_multiplier", "label": "Sales multiplier", "type": "multiplier",
             "value": 1.15, "sign": 1, "enabled": True, "show": True},
            {"key": "sales_overhead_fixed", "label": "Sales overhead (fixed)",
             "type": "amount", "value": 100, "sign": 1, "enabled": True}]})
    # forced hidden even when sent as shown
    assert all(not f["show"] for f in data["factors"])
    t = compute_totals(data, internal_cost=1800)
    assert t["base"] == 1500
    assert t["sales_markup"] == 325          # 15 % of 1500 + 100
    assert t["total_one_time"] == 1825
    assert all(f["show"] is False for f in t["factors"])
    assert {b["department"]: b["amount"] for b in t["by_department"]} == {
        "Tool Engineer": 1000, "Design": 500}
    assert t["margin_abs"] == 25
    # a multiplier of 0 or empty adds nothing
    data["factors"][0]["value"] = 0
    assert compute_totals(data, 0)["sales_markup"] == 100


async def test_package_zip_offer_breakdown_and_quote_files_pm_told(
        client, offer_world, session_factory):
    cid = offer_world["change_id"]
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "q.pdf")
    with open(path, "wb") as fh:
        fh.write(b"%PDF-quote")
    async with session_factory() as s:
        fav = CostingOffer(position_id=offer_world["position_id"], vendor_name="Hasco",
                           cost=1000, favorite=True, created_by=offer_world["users"]["tool"])
        other = CostingOffer(position_id=offer_world["position_id"], vendor_name="Meusburger",
                             cost=900, created_by=offer_world["users"]["tool"])
        s.add_all([fav, other])
        await s.flush()
        s.add(ChangeAttachment(
            change_id=cid, filename="hasco-quote.pdf", stored_path=path,
            content_type="application/pdf", size_bytes=10, sha256="x" * 64,
            phase="post_scoping", kind="vendor_quote", costing_offer_id=fav.id,
            uploaded_by=offer_world["users"]["tool"]))
        s.add(ChangeAttachment(
            change_id=cid, filename="other.pdf", stored_path=path,
            content_type="application/pdf", size_bytes=10, sha256="y" * 64,
            phase="post_scoping", kind="vendor_quote", costing_offer_id=other.id,
            uploaded_by=offer_world["users"]["tool"]))
        await s.commit()
    sales = await _auth(client, "sales")
    await _seed_quote_plan(client, sales, cid)
    o = await _create(client, sales, cid)
    line = next(l for l in o["data"]["cost_lines"] if l.get("position_id"))
    # both quotes offered to Sales, the favourite preselected
    assert {q["vendor"] for q in line["quotes"]} == {"Hasco", "Meusburger"}
    assert line["block"] == "supplier"
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "risks": [{"key": "own:1", "source": "sales", "label": "Resin not released",
                   "show": True, "type": "amount", "value": 0}],
        "other_notes": "Excludes PPAP level 3."}}, headers=sales)
    assert res.status_code == 200, res.text
    res = await client.get(_url(cid, f"/{o['id']}/package"), headers=sales)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(res.content))
    names = z.namelist()
    assert "C-O-1-offer-v1.pdf" in names
    assert "C-O-1-offer-v1-internal-breakdown.csv" in names
    # only the favourite's file, named department - vendor - line
    assert "supplier-quotes/Tool Engineer - Hasco - Insert rework.pdf" in names
    assert not any("Meusburger" in n for n in names)
    csv_text = z.read("C-O-1-offer-v1-internal-breakdown.csv").decode("utf-8-sig")
    assert "Margin" in csv_text and "Tool Engineer" in csv_text
    pypdf = pytest.importorskip("pypdf")
    text = "".join(p.extract_text() for p in pypdf.PdfReader(
        io.BytesIO(z.read("C-O-1-offer-v1.pdf"))).pages)
    assert "Resin not released" in text and "Excludes PPAP level 3." in text
    assert "Sales multiplier" not in text
    # PM may read it too; a stranger without price rights may not
    pm = await _auth(client, "pm")
    assert (await client.get(_url(cid, f"/{o['id']}/package"), headers=pm)).status_code == 200
    tool = await _auth(client, "tool")
    assert (await client.get(_url(cid, f"/{o['id']}/package"), headers=tool)).status_code == 403
    # finishing = sending: quoted, stamped, PM told who and when
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={}, headers=sales)
    assert res.status_code == 200, res.text
    assert res.json()["sent_by_name"] == "Offer sales" and res.json()["sent_at"]
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.subject_key == f"offer_sent:{cid}:1"))).scalars().all()
    assert notes and all(n.user_id != offer_world["users"]["sales"] for n in notes)
    assert "sent by Offer sales" in notes[0].body


async def test_changeover_is_one_sentence_the_customer_is_tied_to():
    from app.services.offer_pdf import changeover_sentence
    run = changeover_sentence({"mode": "running_change", "scrap_qty": 1200,
                               "changeover_date": "2026-12-01"}, "EUR")
    assert run.startswith("Running change: the remaining 1")
    assert "used up" in run and "1 Dec 2026" in run
    scrap = changeover_sentence({"mode": "customer_pays_scrap", "scrap_qty": 50,
                                 "scrap_unit_price": 2}, "EUR")
    assert scrap.startswith("Customer scraps the old stock: the remaining 50 old parts")
    assert "100" in scrap
    assert changeover_sentence({"mode": "running_change"}, "EUR") == (
        "Running change: the existing stock is used up before the changed part is introduced.")


async def test_customer_timing_includes_the_buffer_and_never_draws_it(
        client, offer_world, session_factory):
    import math
    from app.models.change import ChangeRequest
    from app.services.offer_service import OfferService
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    await _seed_quote_plan(client, sales, cid)
    o = await _create(client, sales, cid)
    tm = o["data"]["timing"]
    assert tm["total_weeks"] >= tm["real_weeks"]
    assert tm["weeks_from_order"] == max(1, math.ceil(tm["total_weeks"]))
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        snap = await OfferService._snapshot(s, change)
    assert not any(t["kind"] == "buffer" for t in snap["tasks"])
    assert all(t["name"].endswith("(estimate, floats with the PO)")
               for t in snap["tasks"] if t["kind"] == "bank_build")
