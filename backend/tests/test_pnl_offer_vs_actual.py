"""P&L rough cut (spec §13): the offer (frozen at acceptance) against what the
change really cost: booked hours x rate, supplier invoices, scrap and
validation issue costs; margins, slip, rights and the list columns."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine, DepartmentRate
from app.models.change_impl import ImplementationBooking
from app.models.change_offer import ChangeOffer
from app.models.change_plan import ChangePlanTask
from app.models.entities import Plant
from app.models.workflow import Department, UserDepartment
from app.services.offer_service import SNAPSHOT_KEY, OfferService, default_data
from app.services.pnl_service import PnlService, compose
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def world(session_factory, seed):
    """A customer change priced at 1000 internal + 500 external, offer v1
    sent at 3000 and accepted (which freezes the plan)."""
    async with session_factory() as s:
        tool = Department(name="Tooling-OVA", flow_type="action")
        other = Department(name="Other-OVA", flow_type="action")
        s.add_all([tool, other])
        await s.flush()
        plant_id = (await s.execute(select(Plant.id))).scalars().first()
        s.add(DepartmentRate(department_id=tool.id, plant_id=plant_id,
                             hourly_rate=100.0, effective_from=date(2020, 1, 1)))
        change = ChangeRequest(
            change_number="CR-OVA-1", title="Offer vs doing", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="quoted", customer_relevant=True,
            quoted_price=3000.0, raised_at=datetime(2026, 5, 1))
        s.add(change)
        await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=tool.id,
                             verdict="feasible")
        s.add(a)
        await s.flush()
        s.add(AssessmentCostLine(
            assessment_id=a.id, plant_id=plant_id, cost_kind="one_time",
            demand_hours=10.0, rate_snapshot=100.0,
            internal_cost=1000.0, external_cost=500.0))
        data = default_data()
        data["cost_lines"] = [{"key": "x", "label": "x", "category": "internal",
                               "amount": 3000, "include": True}]
        data[SNAPSHOT_KEY] = {"taken_at": "2026-05-02T00:00:00"}
        offer = ChangeOffer(change_id=change.id, version=1, status="sent",
                            data=data, total_one_time=3000.0,
                            created_by=seed["admin_id"],
                            received_at=date.today(),
                            valid_until=date.today() + timedelta(days=30))
        s.add(offer)
        await s.flush()
        await OfferService.apply_customer_response(
            s, change, "accepted", seed["admin_id"], None)
        await s.commit()
        return {"change_id": change.id, "offer_id": offer.id,
                "tool_id": tool.id, "other_id": other.id, **seed}


async def _status(session_factory, change_id, status):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, change_id)
        c.status = status
        await s.commit()


async def test_acceptance_freezes_the_plan(session_factory, world):
    async with session_factory() as s:
        offer = await s.get(ChangeOffer, world["offer_id"])
        pnl = offer.data[SNAPSHOT_KEY]["pnl"]
        assert offer.status == "accepted"
        assert pnl["revenue"] == 3000.0
        assert pnl["internal"] == 1000.0
        assert pnl["external"] == 500.0
        assert offer.data[SNAPSHOT_KEY]["taken_at"] == "2026-05-02T00:00:00"
        # a second freeze never overwrites the first
        change = await s.get(ChangeRequest, world["change_id"])
        s.add(AssessmentCostLine(
            assessment_id=(await s.execute(select(ChangeAssessment.id).where(
                ChangeAssessment.change_id == change.id))).scalar_one(),
            plant_id=(await s.execute(select(Plant.id))).scalars().first(),
            cost_kind="one_time", demand_hours=1, rate_snapshot=1,
            internal_cost=999.0, external_cost=0.0))
        await s.flush()
        again = await OfferService.freeze_pnl(s, change, offer)
        assert again["internal"] == 1000.0


async def test_plan_phase_before_implementation(client, admin_auth, world):
    r = await client.get(
        f"/api/v1/pnl/changes/{world['change_id']}/offer-vs-actual", headers=admin_auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phase"] == "plan"
    assert body["basis"] == "accepted_offer"
    assert body["offer_version"] == 1
    assert body["planned_margin"] == 1500.0
    keys = [l["key"] for l in body["lines"]]
    assert keys[:4] == ["revenue", "internal", "external", "scrap"]
    assert {"issues_internal", "issues_supplier", "issues_customer"} <= set(keys)


async def test_offer_vs_actual_in_implementation(client, admin_auth, session_factory, world):
    await _status(session_factory, world["change_id"], "in_implementation")
    async with session_factory() as s:
        s.add(ImplementationBooking(change_id=world["change_id"],
                                    department_id=world["tool_id"], hours=12.0,
                                    booked_by=world["admin_id"]))
        await s.commit()
    r = await client.post(
        f"/api/v1/changes/{world['change_id']}/actual-costs",
        json={"category": "external", "amount": 700, "cost_date": "2026-06-01",
              "vendor_name": "Hasco", "department_id": world["tool_id"]},
        headers=admin_auth)
    assert r.status_code == 201, r.text
    assert r.json()["vendor_name"] == "Hasco"
    assert r.json()["can_delete"] is True

    body = (await client.get(
        f"/api/v1/pnl/changes/{world['change_id']}/offer-vs-actual",
        headers=admin_auth)).json()
    by = {l["key"]: l for l in body["lines"]}
    assert body["phase"] == "actual"
    assert by["internal"]["planned"] == 1000.0 and by["internal"]["actual"] == 1200.0
    assert by["external"]["actual"] == 700.0 and by["external"]["variance"] == 200.0
    assert body["actual_margin"] == 1100.0
    assert body["variance"] == -400.0
    assert body["booked_hours"] == 12.0


async def test_rights(client, admin_auth, session_factory, world):
    await _status(session_factory, world["change_id"], "in_implementation")
    # admin hub cookie, but the local row is an engineer: no cost role
    eng = await login(client, "eng@test.io")
    cid = world["change_id"]
    assert (await client.get(f"/api/v1/pnl/changes/{cid}/offer-vs-actual",
                             headers=eng)).status_code == 403
    assert (await client.get(f"/api/v1/changes/{cid}/actual-costs",
                             headers=eng)).status_code == 403
    body = {"category": "external", "amount": 50, "cost_date": "2026-06-02",
            "department_id": world["tool_id"]}
    assert (await client.post(f"/api/v1/changes/{cid}/actual-costs",
                              json=body, headers=eng)).status_code == 403
    async with session_factory() as s:
        s.add(UserDepartment(user_id=world["engineer_id"],
                             department_id=world["tool_id"]))
        await s.commit()
    r = await client.post(f"/api/v1/changes/{cid}/actual-costs", json=body, headers=eng)
    assert r.status_code == 201, r.text
    own_id = r.json()["id"]
    # not their department
    r = await client.post(f"/api/v1/changes/{cid}/actual-costs",
                          json={**body, "department_id": world["other_id"]}, headers=eng)
    assert r.status_code == 403
    # a line the admin entered is not theirs to delete
    r = await client.post(f"/api/v1/changes/{cid}/actual-costs",
                          json={**body, "department_id": world["other_id"]},
                          headers=admin_auth)
    admin_row = r.json()["id"]
    listing = (await client.get(f"/api/v1/changes/{cid}/actual-costs", headers=eng)).json()
    assert [i["id"] for i in listing["items"]] == [own_id]
    assert listing["writable_department_ids"] == [world["tool_id"]]
    assert (await client.delete(f"/api/v1/changes/{cid}/actual-costs/{admin_row}",
                                headers=eng)).status_code == 403
    assert (await client.delete(f"/api/v1/changes/{cid}/actual-costs/{own_id}",
                                headers=eng)).status_code == 204
    full = (await client.get(f"/api/v1/changes/{cid}/actual-costs",
                             headers=admin_auth)).json()
    assert [i["id"] for i in full["items"]] == [admin_row]


async def test_write_window_and_validation(client, admin_auth, world):
    cid = world["change_id"]              # still 'quoted'
    body = {"category": "external", "amount": 50, "cost_date": "2026-06-02"}
    assert (await client.post(f"/api/v1/changes/{cid}/actual-costs", json=body,
                              headers=admin_auth)).status_code == 400
    assert (await client.post(f"/api/v1/changes/{cid}/actual-costs",
                              json={**body, "amount": 0},
                              headers=admin_auth)).status_code == 422
    assert (await client.post(f"/api/v1/changes/{cid}/actual-costs",
                              json={**body, "category": "beer"},
                              headers=admin_auth)).status_code == 422


async def test_validation_issue_costs_by_bearer(client, admin_auth, session_factory, world):
    from app.models.database import Base
    tbl = Base.metadata.tables.get("change_validation_issues")
    if tbl is None:
        pytest.skip("validation issues not in this build")
    await _status(session_factory, world["change_id"], "in_validation")
    async with session_factory() as s:
        for n, (amount, bearer, quoted) in enumerate(
                [(100, "internal", False), (50, "supplier", False),
                 (80, "customer", True), (20, "customer", False)], start=1):
            await s.execute(tbl.insert().values(
                change_id=world["change_id"], number=n, title=f"VI-{n}",
                category="other", severity=2, description="d",
                chargeback=False, customer_inform=False, escalation_level=1,
                status="open", extra_cost=amount, cost_bearer=bearer,
                fix_quoted_at=datetime.utcnow() if quoted else None,
                created_by=world["admin_id"], created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()))
        await s.commit()
    body = (await client.get(
        f"/api/v1/pnl/changes/{world['change_id']}/offer-vs-actual",
        headers=admin_auth)).json()
    by = {l["key"]: l for l in body["lines"]}
    assert by["issues_internal"]["actual"] == 100.0
    assert by["issues_supplier"]["actual"] == 50.0
    assert by["issues_supplier"]["in_margin"] is False
    assert by["issues_customer"]["actual"] == 100.0
    assert by["revenue"]["actual"] == 3080.0          # quoted part billed
    # 3080 - (0 internal + 0 ext + 100 + 100)
    assert body["actual_margin"] == 2880.0
    assert any("not quoted" in w for w in body["warnings"])
    assert body["issue_count"] == 4


async def test_slip_against_the_offered_finish(client, admin_auth, session_factory, world):
    await _status(session_factory, world["change_id"], "in_implementation")
    async with session_factory() as s:
        s.add(ChangePlanTask(change_id=world["change_id"], plan="detailed",
                             name="Tool", kind="work", start_date=date(2026, 7, 1),
                             duration_days=10, baseline_start=date(2026, 7, 1),
                             baseline_finish=date(2026, 7, 8),
                             created_by=world["admin_id"]))
        await s.commit()
    body = (await client.get(
        f"/api/v1/pnl/changes/{world['change_id']}/offer-vs-actual",
        headers=admin_auth)).json()
    assert any("No actuals recorded" in w for w in body["warnings"])
    t = body["timing"]
    assert t["baseline_finish"] == "2026-07-07"
    assert t["forecast_finish"] == "2026-07-10"
    assert t["slip_days"] == 3 and t["unit"] == "calendar days"

    rows = (await client.get("/api/v1/pnl/changes", headers=admin_auth)).json()["rows"]
    row = next(r for r in rows if r["change_id"] == world["change_id"])
    assert row["slip_days"] == 3
    assert row["offer_revenue"] == 3000.0
    assert row["planned_cost"] == 1500.0
    assert row["planned_margin"] == 1500.0
    # nothing booked or invoiced: no actual to compare, not a saving
    assert row["actual_cost"] is None and row["phase"] == "plan"
    assert row["variance"] is None
    summ = (await client.get("/api/v1/pnl/summary", headers=admin_auth)).json()
    assert summ["totals"]["late_count"] == 1
    assert summ["totals"]["offer_revenue"] >= 3000.0


async def test_timing_dates_follow_the_plans_last_day_rule(client, admin_auth, session_factory, world):
    """A milestone sits on its start (change_plan_service._last_day), as the
    Release tab's closing card reads it: the SOP baselined on 13 Jan reads
    13 Jan here too, not 12 Jan."""
    await _status(session_factory, world["change_id"], "in_implementation")
    async with session_factory() as s:
        s.add(ChangePlanTask(change_id=world["change_id"], plan="detailed",
                             name="Tool", kind="work", start_date=date(2027, 1, 1),
                             duration_days=5, baseline_start=date(2027, 1, 1),
                             baseline_finish=date(2027, 1, 6),
                             created_by=world["admin_id"]))
        s.add(ChangePlanTask(change_id=world["change_id"], plan="detailed",
                             name="SOP", kind="milestone", start_date=date(2027, 1, 30),
                             duration_days=0, baseline_start=date(2027, 1, 13),
                             baseline_finish=date(2027, 1, 13),
                             created_by=world["admin_id"]))
        await s.commit()
    t = (await client.get(
        f"/api/v1/pnl/changes/{world['change_id']}/offer-vs-actual",
        headers=admin_auth)).json()["timing"]
    assert t["baseline_finish"] == "2027-01-13"
    assert t["forecast_finish"] == "2027-01-30"
    assert t["slip_days"] == 17
    rows = (await client.get("/api/v1/pnl/changes", headers=admin_auth)).json()["rows"]
    assert next(r for r in rows if r["change_id"] == world["change_id"])["slip_days"] == 17


async def _refreeze(s, change_id, offer_id, **override):
    """Re-take the accepted offer's frozen P&L from the plan as it stands
    (the world fixture froze before any quote plan existed)."""
    change = await s.get(ChangeRequest, change_id)
    offer = await s.get(ChangeOffer, offer_id)
    pnl = await PnlService.planned_figures(s, change, offer)
    pnl.update(override)
    data = dict(offer.data)
    data[SNAPSHOT_KEY] = {**data[SNAPSHOT_KEY], "pnl": pnl}
    offer.data = data
    await s.flush()
    return pnl


async def test_slip_from_a_quote_plan_ending_on_a_milestone(client, admin_auth, session_factory, world):
    """Quote plan ends on a milestone (X), the detailed plan, no baseline yet,
    ends on a milestone (Y): slip is Y - X, not one day more. The frozen
    quote_last_day is the baseline, not the live quote plan."""
    cid = world["change_id"]
    await _status(session_factory, cid, "in_implementation")
    async with session_factory() as s:
        s.add_all([
            ChangePlanTask(change_id=cid, plan="quote", name="Tool", kind="work",
                           start_date=date(2026, 8, 1), duration_days=10,
                           created_by=world["admin_id"]),
            ChangePlanTask(change_id=cid, plan="quote", name="SOP", kind="milestone",
                           start_date=date(2026, 8, 20), duration_days=0,
                           created_by=world["admin_id"]),
            ChangePlanTask(change_id=cid, plan="detailed", name="SOP", kind="milestone",
                           start_date=date(2026, 8, 25), duration_days=0,
                           created_by=world["admin_id"]),
        ])
        await s.flush()
        pnl = await _refreeze(s, cid, world["offer_id"])
        assert pnl["quote_last_day"] == "2026-08-20"
        assert pnl["quote_finish"] == "2026-08-20"     # end_date: milestone on its start
        # the live quote plan moving after acceptance does not move the baseline
        sop = (await s.execute(select(ChangePlanTask).where(
            ChangePlanTask.change_id == cid, ChangePlanTask.plan == "quote",
            ChangePlanTask.name == "SOP"))).scalar_one()
        sop.start_date = date(2026, 9, 1)
        await s.commit()
    t = (await client.get(f"/api/v1/pnl/changes/{cid}/offer-vs-actual",
                          headers=admin_auth)).json()["timing"]
    assert t["baseline_finish"] == "2026-08-20"
    assert t["forecast_finish"] == "2026-08-25"
    assert t["slip_days"] == 5
    rows = (await client.get("/api/v1/pnl/changes", headers=admin_auth)).json()["rows"]
    assert next(r for r in rows if r["change_id"] == cid)["slip_days"] == 5


async def test_old_snapshot_without_quote_last_day_keeps_the_exclusive_end_fallback(
        client, admin_auth, session_factory, world):
    """A snapshot frozen before quote_last_day existed has only quote_finish
    (an exclusive end): the baseline is quote_finish - 1 day."""
    cid = world["change_id"]
    await _status(session_factory, cid, "in_implementation")
    async with session_factory() as s:
        s.add(ChangePlanTask(change_id=cid, plan="detailed", name="SOP", kind="milestone",
                             start_date=date(2026, 7, 14), duration_days=0,
                             created_by=world["admin_id"]))
        await s.flush()
        await _refreeze(s, cid, world["offer_id"], quote_finish="2026-07-11",
                        quote_last_day=None)
        await s.commit()
    t = (await client.get(f"/api/v1/pnl/changes/{cid}/offer-vs-actual",
                          headers=admin_auth)).json()["timing"]
    assert t["baseline_finish"] == "2026-07-10"
    assert t["slip_days"] == 4
    rows = (await client.get("/api/v1/pnl/changes", headers=admin_auth)).json()["rows"]
    assert next(r for r in rows if r["change_id"] == cid)["slip_days"] == 4


async def test_changes_without_frozen_plan_fall_back_to_costing(session_factory, seed):
    async with session_factory() as s:
        c = ChangeRequest(
            change_number="CR-OVA-2", title="Old", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_implementation",
            customer_relevant=True, quoted_price=900.0)
        s.add(c)
        await s.flush()
        out = await PnlService.offer_vs_actual(s, c)
        assert out["basis"] == "costing"
        assert out["planned_revenue"] == 900.0
        assert any("No accepted offer" in w for w in out["warnings"])


async def test_compose_is_pure_and_keeps_info_out_of_margin():
    out = compose({"revenue": 100, "internal": 40, "external": 10, "scrap": 0},
                  {"revenue": 100, "internal": 50, "external": 10, "scrap": 5,
                   "issues_supplier": 1000})
    assert out["planned_margin"] == 50.0
    assert out["actual_margin"] == 35.0
    assert out["variance"] == -15.0
    no_price = compose({"revenue": None}, {"revenue": None, "internal": 5})
    assert no_price["planned_margin"] is None and no_price["variance"] is None


async def test_compose_in_progress_counts_open_lines_at_plan():
    out = compose({"revenue": 100, "internal": 40, "external": 10},
                  {"revenue": 100, "internal": 5, "external": 20}, in_progress=True)
    by = {l["key"]: l for l in out["lines"]}
    assert by["internal"]["forecast"] == 40.0 and by["internal"]["variance"] == 0.0
    assert by["external"]["variance"] == 10.0          # an overrun still shows
    assert out["actual_margin"] == 75.0                # to date
    assert out["forecast_margin"] == 40.0
    assert out["variance"] == -10.0
