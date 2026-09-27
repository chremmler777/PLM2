"""Two-currency plants (106): Silao quotes in USD and pays in MXN. A cost
sheet version carries its exchange rates (typed on the draft, frozen on
publish); a rate may be typed in either currency and the typed number is
kept, the other computed, never drifting; costing reads the quote
currency; the P&L converts MXN actual costs at the change's version's rate
and says so."""
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.change_actual_cost import ChangeActualCost
from app.models.cost_sheet import CostSheetRate, CostSheetVersion
from app.models.entities import Plant, Project
from app.models.workflow import Department
from app.services import cost_sheet_service as svc
from app.services.pnl_service import PnlService

pytestmark = pytest.mark.asyncio
API = "/api/v1/cost-sheet"


@pytest.fixture
async def world(session_factory, seed):
    async with session_factory() as s:
        tool = Department(name="Tool-FX", flow_type="action")
        s.add(tool)
        home = (await s.execute(select(Plant))).scalars().first()
        silao = Plant(organization_id=seed["org_id"], name="Silao Mexico", code="SIL",
                      location="MX", is_active=True, currency="USD", local_currency="MXN")
        s.add(silao)
        await s.commit()
        return {**seed, "tool": tool.id, "home": home.id, "silao": silao.id}


def _row(rows, dep, plant):
    return next(r for r in rows if r["department_id"] == dep and r["plant_id"] == plant)


async def test_plant_local_currency_is_set_and_cleared(client, admin_auth, world):
    res = await client.put(f"{API}/plants/{world['home']}/currency",
                           json={"currency": "usd", "local_currency": "mxn"}, headers=admin_auth)
    home = next(p for p in res.json() if p["id"] == world["home"])
    assert (home["currency"], home["local_currency"]) == ("USD", "MXN")
    # left out: unchanged
    res = await client.put(f"{API}/plants/{world['home']}/currency",
                           json={"currency": "USD"}, headers=admin_auth)
    assert next(p for p in res.json() if p["id"] == world["home"])["local_currency"] == "MXN"
    res = await client.put(f"{API}/plants/{world['home']}/currency",
                           json={"currency": "EUR", "local_currency": None}, headers=admin_auth)
    assert next(p for p in res.json() if p["id"] == world["home"])["local_currency"] is None
    assert (await client.put(f"{API}/plants/{world['home']}/currency",
                             json={"currency": "EUR", "local_currency": "XYZ"},
                             headers=admin_auth)).status_code == 422


async def test_rates_typed_in_either_currency_never_drift(client, admin_auth, world):
    t, silao = world["tool"], world["silao"]
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    base = f"{API}/versions/{d['id']}"
    assert d["fx_needed"] == [{"pair": "USD/MXN", "base": "USD", "quote": "MXN"}]
    row = _row(d["rates"], t, silao)
    assert (row["currency"], row["local_currency"], row["local_rate"]) == ("USD", "MXN", None)
    # no exchange rate yet: a rate typed in MXN cannot be priced
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 1730, "entered_currency": "MXN"}, headers=admin_auth)
    assert res.status_code == 422 and "USD/MXN exchange rate" in res.json()["detail"]
    for bad in ("0", "-2", "abc", "1e9"):
        assert (await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN",
                                                     "rate": bad},
                                 headers=admin_auth)).status_code == 422, bad
    res = await client.put(f"{base}/fx", json={"base": "usd", "quote": "mxn", "rate": "17.30"},
                           headers=admin_auth)
    assert res.json()["fx_rates"] == [{"pair": "USD/MXN", "base": "USD", "quote": "MXN",
                                       "rate": "17.30"}]
    # typed in MXN: kept as typed, USD computed
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 1000, "entered_currency": "MXN"}, headers=admin_auth)
    r = _row(res.json()["rates"], t, silao)
    assert (r["hourly_rate"], r["local_rate"], r["entered_in"]) == (57.8, 1000.0, "local")
    # the exchange rate moves: the typed MXN stays, the USD follows
    res = await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": 20},
                           headers=admin_auth)
    r = _row(res.json()["rates"], t, silao)
    assert (r["hourly_rate"], r["local_rate"]) == (50.0, 1000.0)
    # typed in USD: MXN computed; the typed MXN is gone
    res = await client.patch(f"{base}/rates/{row['id']}", json={"hourly_rate": 60},
                             headers=admin_auth)
    r = _row(res.json()["rates"], t, silao)
    assert (r["hourly_rate"], r["local_rate"], r["entered_in"]) == (60.0, 1200.0, "quote")
    assert r["entered_rate"] is None
    # typed in USD through entered_rate is the same as hourly_rate
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 61, "entered_currency": "USD"}, headers=admin_auth)
    assert _row(res.json()["rates"], t, silao)["hourly_rate"] == 61
    # a currency that is not the plant's local one is refused
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 61, "entered_currency": "EUR"}, headers=admin_auth)
    assert res.status_code == 422
    # clearing the typed rate clears the rate
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": None, "entered_currency": "MXN"}, headers=admin_auth)
    r = _row(res.json()["rates"], t, silao)
    assert r["hourly_rate"] is None and r["local_rate"] is None
    # an all-plants row has no second currency
    all_plants = (await client.post(f"{base}/rates", json={"department_id": t,
                                                           "hourly_rate": 10},
                                    headers=admin_auth)).json()
    assert _row(all_plants["rates"], t, None)["local_currency"] is None


async def test_exchange_rate_is_frozen_with_the_version(client, admin_auth, world,
                                                        session_factory):
    t, silao = world["tool"], world["silao"]
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    base = f"{API}/versions/{d['id']}"
    await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": "17.30"},
                     headers=admin_auth)
    row = _row(d["rates"], t, silao)
    await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 1730, "entered_currency": "MXN"}, headers=admin_auth)
    res = await client.post(f"{base}/publish", json={
        "valid_from": "2026-01-01", "confirm_backdated": True}, headers=admin_auth)
    assert res.status_code == 200
    assert (await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": 18},
                             headers=admin_auth)).status_code == 409
    # the next draft starts from the same exchange rate and typed numbers
    d2 = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    assert d2["fx_rates"][0]["rate"] == "17.30"
    r = _row(d2["rates"], t, silao)
    assert (r["hourly_rate"], r["local_rate"], r["entered_in"]) == (100.0, 1730.0, "local")
    # a new exchange rate alone is a change worth publishing, and the diff says so
    res = await client.put(f"{API}/versions/{d2['id']}/fx", json={
        "base": "USD", "quote": "MXN", "rate": "18.00"}, headers=admin_auth)
    assert _row(res.json()["rates"], t, silao)["hourly_rate"] == 96.11
    diff = (await client.get(f"{API}/versions/{d2['id']}/diff", headers=admin_auth)).json()
    assert diff["fx_rates"] == [{"pair": "USD/MXN", "old": "17.30", "new": "18.00"}]
    res = await client.post(f"{API}/versions/{d2['id']}/publish", json={
        "valid_from": "2026-06-01", "confirm_backdated": True}, headers=admin_auth)
    assert res.status_code == 200
    # the old version still converts at its own rate
    async with session_factory() as s:
        v1 = await s.get(CostSheetVersion, d["id"])
        assert svc.convert(v1, 1730, "MXN", "USD") == 100.0
        assert svc.convert(v1, 100, "USD", "MXN") == 1730.0
        assert svc.convert(v1, 100, "USD", "EUR") is None      # no rate: none


async def test_publish_refuses_a_typed_rate_without_its_exchange_rate(
        session_factory, world):
    async with session_factory() as s:
        v = await svc.create_draft(s, world["org_id"], None)
        await svc.set_fx_rate(s, v, "USD", "MXN", "17.30")
        row = next(r for r in v.rates if r.department_id == world["tool"]
                   and r.plant_id == world["silao"])
        await svc.update_row(s, v, "rates", row.id,
                             {"entered_rate": 1730, "entered_currency": "MXN"})
        other = next(r for r in v.rates if r.department_id == world["tool"]
                     and r.plant_id == world["home"])
        await svc.update_row(s, v, "rates", other.id, {"hourly_rate": 5})
        await svc.set_fx_rate(s, v, "USD", "MXN", None)
        await s.refresh(v)
        assert row.hourly_rate is None and row.entered_rate == 1730
        with pytest.raises(svc.CostSheetError) as e:
            await svc.publish(s, v, None, date(2026, 1, 1), confirm_backdated=True)
        assert "exchange rate" in e.value.message


async def test_pnl_converts_mxn_actual_costs_at_the_change_version(
        world, session_factory):
    async with session_factory() as s:
        project = Project(plant_id=world["silao"], name="Silao job", code="SIL-1")
        s.add(project)
        await s.flush()
        change = ChangeRequest(change_number="C-FX-1", title="fx", reason="r",
                               change_type="physical_part", project_id=project.id,
                               raised_by=world["admin_id"], lead_id=world["admin_id"],
                               status="in_implementation",
                               created_at=datetime(2026, 3, 1, 12))
        s.add(change)
        await s.flush()
        for amount, cur in ((1730, "MXN"), (50, "USD"), (10, "EUR")):
            s.add(ChangeActualCost(change_id=change.id, category="external", amount=amount,
                                   currency=cur, cost_date=date(2026, 4, 1),
                                   created_by=world["admin_id"]))
        for number, valid_from, rate in ((1, date(2026, 1, 1), "17.30"),
                                         (2, date(2026, 6, 1), "20.00")):
            v = CostSheetVersion(organization_id=world["org_id"], version=number,
                                 status="published", valid_from=valid_from,
                                 published_at=datetime(2026, 1, 1), fx_rates={"USD/MXN": rate})
            s.add(v)
            await s.flush()
            s.add(CostSheetRate(version_id=v.id, department_id=world["tool"],
                                hourly_rate=10, currency="USD"))
        await s.commit()
        cid = change.id
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        card = await PnlService.offer_vs_actual(s, change)
        # created in March: v1's 17.30, not v2's 20.00
        assert card["fx_notes"] == [
            "1,730.00 MXN of actual costs converted to 100.00 USD at 17.30 MXN per USD "
            "(cost sheet v1)"]
        external = next(l for l in card["lines"] if l["key"] == "external")
        assert external["actual"] == 150.0
        # EUR has no rate in the version: left out and warned, never added
        assert any("EUR" in w and "no conversion" in w for w in card["warnings"])
        assert not any("MXN" in w for w in card["warnings"])


async def test_implausible_or_inverted_exchange_rate_is_refused(client, admin_auth, world):
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    base = f"{API}/versions/{d['id']}"
    # typed the wrong way round (MXN per USD expected 5..50)
    res = await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": "0.058"},
                           headers=admin_auth)
    assert res.status_code == 422
    assert "1 USD is expected to be between 5 and 50 MXN" in res.json()["detail"]
    res = await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": "173"},
                           headers=admin_auth)
    assert res.status_code == 422
    # the inverse pair is checked the other way round
    res = await client.put(f"{base}/fx", json={"base": "MXN", "quote": "USD", "rate": "17.3"},
                           headers=admin_auth)
    assert res.status_code == 422
    res = await client.put(f"{base}/fx", json={"base": "MXN", "quote": "USD", "rate": "0.0578"},
                           headers=admin_auth)
    assert res.status_code == 200


async def test_fx_rate_that_takes_a_row_out_of_bounds_is_refused(
        client, admin_auth, world, session_factory):
    t, silao = world["tool"], world["silao"]
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    base = f"{API}/versions/{d['id']}"
    await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": "20"},
                     headers=admin_auth)
    row = _row(d["rates"], t, silao)
    await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 1000, "entered_currency": "MXN"}, headers=admin_auth)
    # a typed MXN rate near the column's bound, then a rate that overflows it
    async with session_factory() as s:
        r = await s.get(CostSheetRate, row["id"])
        r.entered_rate = 9_000_000_000
        await s.commit()
    res = await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": "5"},
                           headers=admin_auth)
    assert res.status_code == 422 and "out of range" in res.json()["detail"]
    async with session_factory() as s:
        v = await s.get(CostSheetVersion, d["id"])
        assert v.fx_rates == {"USD/MXN": "20"}        # nothing changed


async def test_rows_off_their_plant_currency_are_flagged_and_mxn_typing_asks_to_switch(
        client, admin_auth, world, session_factory):
    t, silao = world["tool"], world["silao"]
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    base = f"{API}/versions/{d['id']}"
    await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": "17.30"},
                     headers=admin_auth)
    row = _row(d["rates"], t, silao)
    # a Silao row still in EUR (copied from before the currency decision)
    async with session_factory() as s:
        r = await s.get(CostSheetRate, row["id"])
        r.currency, r.hourly_rate = "EUR", 40
        await s.commit()
    detail = (await client.get(f"{base}", headers=admin_auth)).json()
    assert {"section": "rates", "row_id": row["id"], "plant_id": silao,
            "plant_name": "Silao Mexico", "currency": "EUR",
            "plant_currency": "USD"} in detail["currency_mismatch"]
    # MXN typed on it: switch the row to USD first
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 1000, "entered_currency": "MXN"}, headers=admin_auth)
    assert res.status_code == 422
    assert "switch the row to USD first" in res.json()["detail"]
    res = await client.patch(f"{base}/rates/{row['id']}", json={"currency": "USD"},
                             headers=admin_auth)
    assert res.status_code == 200, res.text
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 1000, "entered_currency": "MXN"}, headers=admin_auth)
    assert res.status_code == 200 and not res.json()["currency_mismatch"]


async def test_currency_mismatch_leaves_out_retired_departments(
        client, admin_auth, world, session_factory):
    """A retired department's rows are hidden in the draft: the banner does
    not count rows nobody sees."""
    silao = world["silao"]
    async with session_factory() as s:
        old = Department(name="Retired-FX", flow_type="action", is_active=False)
        s.add(old)
        await s.commit()
        old_id = old.id
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    async with session_factory() as s:
        s.add(CostSheetRate(version_id=d["id"], department_id=old_id, plant_id=silao,
                            hourly_rate=40, currency="EUR"))
        r = await s.get(CostSheetRate, _row(d["rates"], world["tool"], silao)["id"])
        r.currency, r.hourly_rate = "EUR", 41
        await s.commit()
    detail = (await client.get(f"{API}/versions/{d['id']}", headers=admin_auth)).json()
    rows = [m for m in detail["currency_mismatch"] if m["section"] == "rates"]
    assert [m["row_id"] for m in rows] == [_row(d["rates"], world["tool"], silao)["id"]]


async def test_note_only_edit_of_a_mismatched_row_is_not_refused(
        client, admin_auth, world, session_factory):
    """A row off its plant's quote currency that carries a typed MXN rate:
    a note-only edit (the client may resend the unchanged row) moves no
    price and is not re-checked; typing a new rate still is."""
    t, silao = world["tool"], world["silao"]
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    base = f"{API}/versions/{d['id']}"
    await client.put(f"{base}/fx", json={"base": "USD", "quote": "MXN", "rate": "17.30"},
                     headers=admin_auth)
    row = _row(d["rates"], t, silao)
    async with session_factory() as s:
        r = await s.get(CostSheetRate, row["id"])
        r.currency, r.hourly_rate = "EUR", 40
        r.entered_rate, r.entered_currency = 700, "MXN"
        await s.commit()
    res = await client.patch(f"{base}/rates/{row['id']}", json={"note": "checked"},
                             headers=admin_auth)
    assert res.status_code == 200, res.text
    # the whole row resent with only the note changed: still no price move
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "note": "checked again", "currency": "EUR", "hourly_rate": 40,
        "entered_rate": 700, "entered_currency": "MXN"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    r = _row(res.json()["rates"], t, silao)
    assert (r["hourly_rate"], r["currency"], r["note"]) == (40, "EUR", "checked again")
    res = await client.patch(f"{base}/rates/{row['id']}", json={
        "entered_rate": 800, "entered_currency": "MXN"}, headers=admin_auth)
    assert res.status_code == 422 and "switch the row to USD first" in res.json()["detail"]


def test_fx_labels_read_the_direction_and_four_decimals():
    from app.services.costing_rates import fx_direction, fmt_fx
    assert fx_direction("17.30", "USD", "MXN") == "1 USD = 17.30 MXN"
    # an inverted pair is turned back instead of 0.0578...
    assert fx_direction("0.05780346820809248554913294798", "MXN", "USD") \
        == "1 USD = 17.30 MXN"
    assert fmt_fx("0.05780346820809248554913294798") == "0.0578"


def test_converted_line_is_rounded_once():
    from app.services.costing_rates import Price, amount_of
    # 3 h at 1,000 MXN at 17.30: 3,000 / 17.30 = 173.41 (not 3 x 57.80 = 173.40)
    p = Price(rate=57.80, currency="USD", source="cost_sheet",
              detail={"fx": {"from_currency": "MXN", "from_rate": 1000, "rate": "17.30"}})
    assert amount_of(3, p) == 173.41
    assert amount_of(3, Price(rate=57.80, currency="USD", source="cost_sheet")) == 173.40
