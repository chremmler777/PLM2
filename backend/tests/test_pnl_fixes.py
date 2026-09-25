"""P&L fixes from the 2dd5ed3c review: list and card on one basis/phase rule
(B4), the summary's offer-vs-doing margin over the priced rows only, the
margin row's actual and forecast columns, and the actual-cost input rules
(B11: amount bound, German amounts, the attachment's change, own lines)."""
from datetime import datetime

import pytest

from app.auth.security import get_password_hash
from app.models.change import ChangeAttachment, ChangeRequest
from app.models.entities import User
from app.models.workflow import UserDepartment
from app.services.pnl_service import PnlService, compose, pnl_basis, pnl_phase
from tests.conftest import ENGINEER_PASSWORD, login
from tests.test_pnl_offer_vs_actual import _status, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _row(client, auth, cid):
    rows = (await client.get("/api/v1/pnl/changes", headers=auth)).json()["rows"]
    return next(r for r in rows if r["change_id"] == cid)


async def _card(client, auth, cid):
    return (await client.get(f"/api/v1/pnl/changes/{cid}/offer-vs-actual",
                             headers=auth)).json()


async def test_list_and_card_share_basis_and_phase(client, admin_auth, session_factory,
                                                   world, seed):
    cid = world["change_id"]
    for status in ("quoted", "in_implementation"):
        await _status(session_factory, cid, status)
        row, card = await _row(client, admin_auth, cid), await _card(client, admin_auth, cid)
        assert row["basis"] == card["basis"] == "accepted_offer"
        # in implementation with nothing recorded: plan on both, not a saving
        assert row["phase"] == card["phase"] == "plan"
    assert any("No actuals recorded" in w for w in card["warnings"])
    r = await client.post(f"/api/v1/changes/{cid}/actual-costs", headers=admin_auth,
                          json={"category": "external", "amount": 100,
                                "cost_date": "2026-06-01"})
    assert r.status_code == 201, r.text
    row, card = await _row(client, admin_auth, cid), await _card(client, admin_auth, cid)
    assert row["phase"] == card["phase"] == "actual"
    assert row["actual_margin"] == card["actual_margin"]
    # an internal change approved without an offer
    async with session_factory() as s:
        c = ChangeRequest(change_number="CR-INT-1", title="Internal", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], status="approved",
                          customer_relevant=False, internal_approved_amount=800.0)
        s.add(c)
        await s.commit()
        iid = c.id
    row, card = await _row(client, admin_auth, iid), await _card(client, admin_auth, iid)
    assert row["basis"] == card["basis"] == "internal_approval"
    assert row["phase"] == card["phase"] == "plan"


async def test_basis_and_phase_rules():
    class C:
        customer_relevant = True
        internal_approved_amount = None
        status = "in_validation"
    class O:                                             # noqa: E306
        status = "accepted"
    assert pnl_basis(C, O, True) == "accepted_offer"
    assert pnl_basis(C, O, False) == "costing"
    O.status = "sent"
    assert pnl_basis(C, O, False) == "sent_offer"
    assert pnl_basis(C, None, False) == "costing"
    C.customer_relevant, C.internal_approved_amount = False, 5.0
    assert pnl_basis(C, None, False) == "internal_approval"
    assert pnl_phase(C, False) == "plan" and pnl_phase(C, True) == "actual"
    C.status = "approved"
    assert pnl_phase(C, True) == "plan"


async def test_summary_margin_over_priced_rows_only(client, admin_auth, session_factory,
                                                    world, seed):
    async with session_factory() as s:
        s.add(ChangeRequest(change_number="CR-NOPRICE", title="No price", reason="r",
                            change_type="physical_part", project_id=seed["project_id"],
                            raised_by=seed["admin_id"], status="costing",
                            customer_relevant=True))
        await s.commit()
    rows = (await client.get("/api/v1/pnl/changes", headers=admin_auth)).json()["rows"]
    summ = (await client.get("/api/v1/pnl/summary", headers=admin_auth)).json()
    t = summ["totals"]
    priced = [r for r in rows if r["offer_revenue"] is not None]
    assert t["priced_count"] == len(priced) and t["unpriced_count"] == len(rows) - len(priced)
    assert t["unpriced_count"] >= 1
    assert t["planned_margin"] == round(t["offer_revenue"] - t["planned_cost"], 2)


async def test_margin_row_separates_actual_and_forecast():
    out = compose({"revenue": 100, "internal": 40, "external": 10},
                  {"revenue": 100, "internal": 5, "external": 20}, in_progress=True)
    m = out["margin_row"]
    assert m["planned"] == 50.0 and m["actual"] == 75.0 and m["forecast"] == 40.0
    assert m["variance"] == -10.0 and m["actual_pct"] == 75.0


# --- actual costs -----------------------------------------------------------------

async def test_amount_bound_and_typed_amounts(client, admin_auth, session_factory, world):
    cid = world["change_id"]
    await _status(session_factory, cid, "in_implementation")
    base = {"category": "external", "cost_date": "2026-06-01"}
    url = f"/api/v1/changes/{cid}/actual-costs"
    r = await client.post(url, headers=admin_auth, json={**base, "amount": "1,234.56"})
    assert r.status_code == 201, r.text
    assert r.json()["amount"] == 1234.56
    r = await client.post(url, headers=admin_auth, json={**base, "amount": "2 500"})
    assert r.status_code == 201 and r.json()["amount"] == 2500.0
    r = await client.post(url, headers=admin_auth, json={**base, "amount": "1.5 €"})
    assert r.status_code == 201 and r.json()["amount"] == 1.5
    # a decimal comma or a German thousands dot is ambiguous: refused
    for bad in ("1.234,56", "2.500", "1,5 €", "0,500"):
        assert (await client.post(url, headers=admin_auth,
                                  json={**base, "amount": bad})).status_code == 422, bad
    assert (await client.post(url, headers=admin_auth,
                              json={**base, "amount": "abc"})).status_code == 422
    assert (await client.post(url, headers=admin_auth,
                              json={**base, "amount": 10_000_000_000})).status_code == 422
    assert (await client.post(url, headers=admin_auth,
                              json={**base, "amount": 9_999_999_999.99})).status_code == 201
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        admin = await s.get(User, world["admin_id"])
        from app.services.pnl_service import ActualCostError, ActualCostService
        with pytest.raises(ActualCostError):
            await ActualCostService.add(s, change, admin, category="external",
                                        amount=1e11, cost_date=datetime(2026, 6, 1).date())


async def test_attachment_must_belong_to_the_change(client, admin_auth, session_factory,
                                                    world, seed):
    cid = world["change_id"]
    await _status(session_factory, cid, "in_implementation")
    async with session_factory() as s:
        other = ChangeRequest(change_number="CR-OTHER", title="o", reason="r",
                              change_type="physical_part", project_id=seed["project_id"],
                              raised_by=seed["admin_id"], status="in_implementation")
        s.add(other)
        await s.flush()
        ids = []
        for change_id in (other.id, cid):
            a = ChangeAttachment(change_id=change_id, filename="inv.pdf", stored_path="x",
                                 content_type="application/pdf", size_bytes=1,
                                 sha256="0" * 64, kind="general", phase="post_scoping",
                                 uploaded_by=seed["admin_id"])
            s.add(a)
            await s.flush()
            ids.append(a.id)
        await s.commit()
    body = {"category": "external", "amount": 10, "cost_date": "2026-06-01"}
    url = f"/api/v1/changes/{cid}/actual-costs"
    r = await client.post(url, headers=admin_auth, json={**body, "attachment_id": ids[0]})
    assert r.status_code == 400 and "attachment" in r.json()["detail"]
    r = await client.post(url, headers=admin_auth, json={**body, "attachment_id": ids[1]})
    assert r.status_code == 201, r.text


async def test_department_member_reads_only_own_lines(client, session_factory, world, seed):
    cid = world["change_id"]
    await _status(session_factory, cid, "in_implementation")
    async with session_factory() as s:
        colleague = User(organization_id=seed["org_id"], username="coll",
                         email="coll@test.io", full_name="Colleague", role="engineer",
                         hashed_password=get_password_hash(ENGINEER_PASSWORD),
                         is_active=True, mfa_enabled=False)
        s.add(colleague)
        await s.flush()
        for uid in (world["engineer_id"], colleague.id):
            s.add(UserDepartment(user_id=uid, department_id=world["tool_id"]))
        await s.commit()
    body = {"category": "external", "amount": 70, "cost_date": "2026-06-01",
            "department_id": world["tool_id"]}
    url = f"/api/v1/changes/{cid}/actual-costs"
    eng = await login(client, "eng@test.io")
    coll = await login(client, "coll@test.io")
    mine = (await client.post(url, headers=eng, json=body)).json()["id"]
    theirs = await client.post(url, headers=coll, json={**body, "amount": 99})
    assert theirs.status_code == 201
    listing = (await client.get(url, headers=eng)).json()
    assert [i["id"] for i in listing["items"]] == [mine]
    assert listing["total"] == 70.0


async def test_amount_currency_sign_is_read_not_dropped(client, admin_auth, session_factory,
                                                        world):
    """B1 review: "$500" on a EUR change was stored as 500 EUR."""
    cid = world["change_id"]
    await _status(session_factory, cid, "in_implementation")
    base = {"category": "external", "cost_date": "2026-06-01"}
    url = f"/api/v1/changes/{cid}/actual-costs"
    # a mark that contradicts the currency sent
    r = await client.post(url, headers=admin_auth,
                          json={**base, "amount": "£500", "currency": "EUR"})
    assert r.status_code == 400 and "GBP" in r.json()["detail"]
    # "$" is not one currency: refused on a EUR change without a currency
    r = await client.post(url, headers=admin_auth, json={**base, "amount": "$500"})
    assert r.status_code == 400 and "USD, CAD, MXN" in r.json()["detail"]
    r = await client.post(url, headers=admin_auth,
                          json={**base, "amount": "$500", "currency": "EUR"})
    assert r.status_code == 400
    # ... read as the dollar currency sent
    r = await client.post(url, headers=admin_auth,
                          json={**base, "amount": "$500", "currency": "usd"})
    assert r.status_code == 201 and r.json()["currency"] == "USD", r.text
    # an unambiguous mark gives the currency when none is sent
    r = await client.post(url, headers=admin_auth, json={**base, "amount": "1,250 GBP"})
    assert r.status_code == 201 and r.json()["currency"] == "GBP"
    assert r.json()["amount"] == 1250
    r = await client.post(url, headers=admin_auth, json={**base, "amount": "€ 12.5"})
    assert r.status_code == 201 and r.json()["currency"] == "EUR"
    r = await client.post(url, headers=admin_auth, json={**base, "amount": "$12 EUR"})
    assert r.status_code == 422
    # the portfolio row says the USD and GBP lines are not in its EUR actual
    row = await _row(client, admin_auth, cid)
    w = next(x for x in row["warnings"] if x["code"] == "other_currency_actual")
    assert "GBP, USD" in w["message"] and "EUR" in w["message"]


async def test_reader_posting_dollar_amount_gets_403_not_the_currency(
        client, session_factory, world):
    """The currency check names the change's costing currency: someone who
    may not enter costs is refused before it runs."""
    cid = world["change_id"]
    await _status(session_factory, cid, "in_implementation")
    eng = await login(client, "eng@test.io")        # no cost role, no department
    r = await client.post(f"/api/v1/changes/{cid}/actual-costs", headers=eng,
                          json={"category": "external", "amount": "$1",
                                "cost_date": "2026-06-01"})
    assert r.status_code == 403, r.text
    assert "EUR" not in r.json()["detail"] and "$" not in r.json()["detail"]


async def test_engineering_review_is_not_price_pending(client, admin_auth, session_factory,
                                                       world, seed):
    async with session_factory() as s:
        s.add_all([
            ChangeRequest(change_number="CR-ER-1", title="Review", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], status="costing",
                          customer_relevant=False, origin="engineering_review"),
            ChangeRequest(change_number="CR-NOPRICE-2", title="No price", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], status="costing",
                          customer_relevant=True, origin="customer")])
        await s.commit()
    rows = (await client.get("/api/v1/pnl/changes", headers=admin_auth)).json()["rows"]
    by_number = {r["change_number"]: r for r in rows}
    review, open_ = by_number["CR-ER-1"], by_number["CR-NOPRICE-2"]
    assert review["origin"] == "engineering_review" and open_["origin"] == "customer"
    assert by_number["CR-OVA-1"]["origin"] == "customer"
    assert review["pending_price"] is False and open_["pending_price"] is True
    t = (await client.get("/api/v1/pnl/summary", headers=admin_auth)).json()["totals"]
    unpriced = [r for r in rows if r["offer_revenue"] is None
                and r["origin"] != "engineering_review"]
    assert t["unpriced_count"] == len(unpriced)
    assert t["priced_count"] + t["unpriced_count"] == len(rows) - 1
