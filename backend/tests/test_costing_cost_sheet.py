"""Cost sheet phase 2 (spec §15, §15a, §15b): costing lines priced from the
Finance cost sheet with a stored rate snapshot, the machine_time and sampling
kinds, "no rate" never counted as 0, currencies grouped not added, offer and
P&L warnings, booking-date pricing of actuals, the Finance review task, and
the 098 data fix for orgs whose department rates carried no date."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeImpactedItem, ChangeRequest
from app.models.change_cost import AssessmentCostLine, CostingPosition, DepartmentRate
from app.models.change_impl import ImplementationBooking
from app.models.change_offer import ChangeOffer
from app.models.cost_sheet import (
    CostSheetMachineClass, CostSheetMachineRate, CostSheetOverhead, CostSheetRate,
    CostSheetSamplingRate, CostSheetVersion,
)
from app.models.entities import Plant, Project
from app.models.part import Part
from app.models.workflow import Department, UserDepartment
from app.services import costing_rates
from app.services.cost_service import CostService
from app.services.offer_service import OfferService, default_data
from app.services.pnl_service import PnlService
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def world(session_factory, seed):
    """A change in costing at a USD plant; Tool Engineer and Quality routed."""
    async with session_factory() as s:
        tool = Department(name="Tool Engineer", flow_type="action", is_active=True)
        qa = Department(name="Quality", flow_type="action", is_active=True)
        fin = Department(name="Finance", flow_type="info", is_active=True)
        s.add_all([tool, qa, fin])
        await s.flush()
        project = await s.get(Project, seed["project_id"])
        home = await s.get(Plant, project.plant_id)
        home.currency = "USD"
        eur = Plant(organization_id=seed["org_id"], name="Weissenburg", code="wug",
                    location="DE", is_active=True, currency="EUR")
        s.add(eur)
        big = CostSheetMachineClass(organization_id=seed["org_id"], name="200-450 t",
                                    tonnage_min=200, tonnage_max=450, sort_order=1)
        small = CostSheetMachineClass(organization_id=seed["org_id"], name="<=200 t",
                                      tonnage_max=200, sort_order=0)
        s.add_all([big, small])
        await s.flush()
        change = ChangeRequest(
            change_number="C-CS-1", title="cost sheet", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="costing")
        s.add(change)
        await s.flush()
        ids = {}
        for d in (tool, qa):
            a = ChangeAssessment(change_id=change.id, department_id=d.id,
                                 stage_order=1, verdict="feasible")
            s.add(a)
            await s.flush()
            ids[d.name] = a.id
        await s.commit()
        return {**seed, "change_id": change.id, "tool": tool.id, "qa": qa.id,
                "fin": fin.id, "home": home.id, "eur": eur.id, "big": big.id,
                "small": small.id, "assessments": ids}


async def _version(session_factory, org_id, *, version=1, valid_from=date(2026, 1, 1),
                   rates=(), overheads=(), machines=(), sampling=()):
    async with session_factory() as s:
        v = CostSheetVersion(organization_id=org_id, version=version, status="published",
                             valid_from=valid_from, published_at=datetime(2026, 1, 1))
        s.add(v)
        await s.flush()
        for r in rates:
            s.add(CostSheetRate(version_id=v.id, **r))
        for o in overheads:
            s.add(CostSheetOverhead(version_id=v.id, **o))
        for m in machines:
            s.add(CostSheetMachineRate(version_id=v.id, **m))
        for sm in sampling:
            s.add(CostSheetSamplingRate(version_id=v.id, **sm))
        await s.commit()
        return v.id


def _url(world, tail=""):
    return f"/api/v1/changes/{world['change_id']}{tail}"


async def _add(client, auth, world, **body):
    payload = {"department_id": world["tool"], "label": "Line", "kind": "own_time", **body}
    res = await client.post(_url(world, "/costing/positions"), json=payload, headers=auth)
    assert res.status_code == 201, res.text
    return res.json()


async def _summation(session_factory, world):
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        return await CostService.summation(s, change)


# ---------------------------------------------------------------- own time

async def test_own_time_priced_from_the_cost_sheet_with_snapshot(
        client, admin_auth, world, session_factory):
    vid = await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=10, currency="USD"),
        dict(department_id=world["tool"], plant_id=world["home"],
             hourly_rate=20, currency="USD")],
        overheads=[dict(kind="percent", value=7.5)])
    # a labour position (an older client) no longer picks a rate: the
    # department's row at the costing plant does
    line = await _add(client, admin_auth, world, hours=5, labour_position="Engineer")
    assert line["rate"] == 21.5 and line["currency"] == "USD"
    assert line["cost_sheet_version_id"] == vid and line["cost_sheet_version"] == 1
    assert line["rate_source"] == "cost_sheet" and line["rate_is_snapshot"]
    assert line["rate_label"] == "Cost sheet v1, Tool Engineer, 21.50 USD/h"
    assert line["line_value"] == 107.5 and line["rate_missing"] is False
    assert line["rate_match"] == "department+plant"

    summ = await _summation(session_factory, world)
    assert summ["currency"] == "USD"
    assert summ["totals"]["one_time_internal"] == 107.5
    assert summ["cost_sheet_versions_used"] == [1]
    assert summ["warnings"] == [] and summ["unpriced_lines"] == []

    # v2 is published backdated over the change's creation date: the costed
    # line keeps its snapshot ...
    await _version(session_factory, world["org_id"], version=2,
                   valid_from=date(2026, 2, 1), rates=[
                       dict(department_id=world["tool"], hourly_rate=30, currency="USD")])
    summ = await _summation(session_factory, world)
    assert summ["totals"]["one_time_internal"] == 107.5
    assert summ["cost_sheet_current_version"] == 2
    # ... a label edit does not re-price it ...
    res = await client.put(_url(world, f"/costing/positions/{line['id']}"),
                           json={"label": "Renamed"}, headers=admin_auth)
    assert res.json()["cost_sheet_version"] == 1
    # ... changing the hours does, from the version valid on the change's
    # creation date
    res = await client.put(_url(world, f"/costing/positions/{line['id']}"),
                           json={"hours": 2}, headers=admin_auth)
    body = res.json()
    assert body["cost_sheet_version"] == 2 and body["rate"] == 30
    assert body["line_value"] == 60


async def test_missing_rate_is_not_zero(client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    line = await _add(client, admin_auth, world, department_id=world["qa"], hours=4)
    assert line["rate"] is None and line["rate_missing"] is True
    assert line["rate_label"] == "No rate in the cost sheet"
    assert line["line_value"] is None
    await _add(client, admin_auth, world, hours=2)            # priced: 100
    summ = await _summation(session_factory, world)
    assert summ["totals"]["one_time_internal"] == 100
    assert [u["position_id"] for u in summ["unpriced_lines"]] == [line["id"]]
    assert summ["unpriced_lines"][0]["message"] == "No rate in the cost sheet"
    assert any(w["code"] == "no_rate" and "not counted" in w["message"]
               for w in summ["warnings"])
    qa = next(p for p in summ["positions_by_department"]
              if p["department_id"] == world["qa"])
    assert qa["unrated_hours"] and qa["unpriced_count"] == 1
    # an empty line (no hours) is not "missing"
    empty = await _add(client, admin_auth, world, department_id=world["qa"])
    assert empty["rate_missing"] is False


async def test_department_rate_only_without_any_cost_sheet(
        client, admin_auth, world, session_factory):
    async with session_factory() as s:
        s.add(DepartmentRate(department_id=world["tool"], plant_id=world["home"],
                             hourly_rate=65, min_factor=1))
        await s.commit()
    line = await _add(client, admin_auth, world, hours=2)
    assert line["rate"] == 65 and line["rate_source"] == "department_rate"
    assert line["cost_sheet_version_id"] is None
    assert line["rate_label"] == "Department rate, Tool Engineer, 65.00 USD/h"
    # once a version exists the old table is never read: no row = no rate
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["qa"], hourly_rate=10, currency="USD")])
    line = await _add(client, admin_auth, world, hours=2)
    assert line["rate"] is None and line["rate_missing"]


# ---------------------------------------------------------------- machine & sampling

async def test_machine_time_and_sampling_lines(client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"],
                   rates=[dict(department_id=world["tool"], hourly_rate=50, currency="USD")],
                   machines=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  hourly_rate=85, currency="USD")],
                   sampling=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  mode="flat", flat_price=1250, currency="USD")])
    # no class on the change and no tonnage: cannot price
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=3)
    assert m["rate"] is None and m["rate_missing"] and m["machine_class_id"] is None
    # the impacted tool's tonnage defaults the class
    async with session_factory() as s:
        tool = Part(part_number="T-1", name="Tool", item_category="tool", part_type="tool",
                    tool_tonnage_class=350, project_id=world["project_id"],
                    created_by=world["admin_id"])
        s.add(tool)
        await s.flush()
        s.add(ChangeImpactedItem(change_id=world["change_id"], part_id=tool.id,
                                 created_by=world["admin_id"]))
        await s.commit()
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["tonnage"] == 350 and ctx["default_machine_class_id"] == world["big"]
    assert ctx["effective_machine_class_id"] == world["big"] and ctx["currency"] == "USD"
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=3,
                   est_cost=999)
    # priced on the change's (default) class, which the line does not own:
    # a later change of the class moves it
    assert m["machine_class_id"] is None and m["machine_class_used_id"] == world["big"]
    assert m["machine_class_from_change"] and m["rate"] == 85
    assert m["line_value"] == 255 and m["est_cost"] is None
    assert m["rate_label"] == "Cost sheet v1, Machine 200-450 t, 85.00 USD/h"
    sp = await _add(client, admin_auth, world, kind="sampling", label="T1", trials=2)
    assert sp["rate"] == 1250 and sp["line_value"] == 2500 and sp["rate_unit"] == "trial"
    assert sp["rate_label"] == "Cost sheet v1, Sampling 200-450 t, 1,250.00 USD/trial"
    # a class without a sampling row cannot price
    bad = await _add(client, admin_auth, world, kind="sampling", label="T2", trials=1,
                     machine_class_id=world["small"])
    assert bad["rate"] is None and bad["rate_missing"]
    summ = await _summation(session_factory, world)
    tool = next(p for p in summ["positions_by_department"]
                if p["department_id"] == world["tool"])
    assert tool["machine_hours"] == 6 and tool["trials"] == 3
    # the first press found no rate when it was added, so it stored no
    # snapshot: it is priced live and now picks up the tonnage default
    assert summ["totals"]["one_time_internal"] == 255 + 255 + 2500
    assert [u["position_id"] for u in summ["unpriced_lines"]] == [bad["id"]]
    # a foreign class is refused
    res = await client.post(_url(world, "/costing/positions"), json={
        "department_id": world["tool"], "label": "x", "kind": "machine_time",
        "hours": 1, "machine_class_id": 99999}, headers=admin_auth)
    assert res.status_code == 400


async def test_change_machine_class_set_and_reset(client, admin_auth, eng_auth, world):
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["small"]}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["effective_machine_class_id"] == world["small"]
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": 12345}, headers=admin_auth)
    assert res.status_code == 422
    # an engineer outside the routed departments may not
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": None}, headers=eng_auth)
    assert res.status_code == 403
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": None}, headers=admin_auth)
    assert res.json()["machine_class_id"] is None


# ---------------------------------------------------------------- currency

async def test_currencies_are_grouped_never_added(client, admin_auth, world,
                                                  session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD"),
        dict(department_id=world["tool"], plant_id=world["eur"], hourly_rate=40,
             currency="EUR")])
    await _add(client, admin_auth, world, hours=2)                        # 100 USD
    # a grid line at the EUR plant
    res = await client.put(
        _url(world, f"/assessments/{world['assessments']['Tool Engineer']}/cost-lines"),
        json={"lines": [{"plant_id": world["eur"], "activity_label": "Rework",
                         "cost_kind": "one_time", "demand_hours": 3}]},
        headers=admin_auth)
    assert res.status_code in (200, 201), res.text
    async with session_factory() as s:
        cl = (await s.execute(select(AssessmentCostLine))).scalars().one()
        assert cl.currency == "EUR" and cl.rate_snapshot == 40
        assert cl.cost_sheet_version_id is not None and cl.rate_source == "cost_sheet"
    summ = await _summation(session_factory, world)
    assert summ["currency"] == "USD" and summ["mixed_currency"]
    assert summ["totals"]["grand_total"] == 100
    assert summ["totals_by_currency"]["EUR"]["grand_total"] == 120
    assert summ["totals_by_currency"]["USD"]["grand_total"] == 100
    assert any(w["code"] == "mixed_currency" and "EUR" in w["message"]
               for w in summ["warnings"])
    eur_plant = next(p for p in summ["by_plant"] if p["plant_id"] == world["eur"])
    assert eur_plant["currency"] == "EUR" and eur_plant["one_time_internal"] == 120

    # offers: seeded in the costing currency; a EUR offer warns
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        change.status = "quoting"
        offer = ChangeOffer(change_id=change.id, version=1, status="draft", currency="EUR",
                            data=default_data(), created_by=world["admin_id"])
        s.add(offer)
        await s.flush()
        out = (await OfferService.serialize(s, change, [offer]))[0]
        codes = {w["code"]: w["message"] for w in out["warnings"]}
        assert "currency_mismatch" in codes and "USD" in codes["currency_mismatch"]
        assert "mixed_currency" in codes
        assert out["costing_currency"] == "USD"
        assert await costing_rates.costing_currency(s, change) == "USD"


async def test_offer_and_pnl_warn_on_an_outdated_cost_sheet(
        client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _add(client, admin_auth, world, hours=2)
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 3, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=55, currency="USD")])
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        change.status = "quoting"
        offer = ChangeOffer(change_id=change.id, version=1, status="draft", currency="USD",
                            data=default_data(), created_by=world["admin_id"])
        s.add(offer)
        await s.flush()
        out = (await OfferService.serialize(s, change, [offer]))[0]
        msgs = [w["message"] for w in out["warnings"] if w["code"] == "cost_sheet_outdated"]
        outdated = ("Costing used cost sheet v1; this change is priced with v2 "
                    "(valid on its creation date)")
        assert msgs == [outdated]
        assert not any(w["code"] == "currency_mismatch" for w in out["warnings"])
        pnl = await PnlService.offer_vs_actual(s, change)
        assert outdated in pnl["warnings"]
        assert pnl["costing_currency"] == "USD"


# ---------------------------------------------------------------- P&L actuals

async def test_actuals_priced_on_the_booking_date(client, admin_auth, world,
                                                  session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")],
        machines=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                       hourly_rate=80, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 6, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD")])
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        change.status = "in_implementation"
        s.add_all([
            # v1 period: 2 h x 50
            ImplementationBooking(change_id=change.id, department_id=world["tool"],
                                  hours=2, booked_by=world["admin_id"],
                                  booked_at=datetime(2026, 3, 10, 12)),
            # v1 period, a labour position (priced as its department) plus
            # machine hours: 1 h x 50 + 2 mh x 80
            ImplementationBooking(change_id=change.id, department_id=world["tool"],
                                  hours=1, labour_position="Toolmaker",
                                  machine_class_id=world["big"], machine_hours=2,
                                  booked_by=world["admin_id"],
                                  booked_at=datetime(2026, 4, 1, 12)),
            # v2 period: 1 h x 60
            ImplementationBooking(change_id=change.id, department_id=world["tool"],
                                  hours=1, booked_by=world["admin_id"],
                                  booked_at=datetime(2026, 7, 1, 12)),
            # no rate for Quality at all: not counted, flagged
            ImplementationBooking(change_id=change.id, department_id=world["qa"],
                                  hours=5, booked_by=world["admin_id"],
                                  booked_at=datetime(2026, 7, 1, 12)),
        ])
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        act = await PnlService.change_actuals(s, change)
        tool = next(d for d in act["departments"] if d["department_id"] == world["tool"])
        assert tool["actual_cost"] == 100 + 50 + 160 + 60
        assert tool["machine_hours"] == 2 and tool["machine_cost"] == 160
        assert tool["rates"] == [50, 60] and tool["hourly_rate"] is None
        qa = next(d for d in act["departments"] if d["department_id"] == world["qa"])
        assert qa["unrated"] and qa["actual_cost"] == 0
        assert act["unrated_hours"] and act["currency"] == "USD"
        assert act["total_machine_hours"] == 2


async def test_booking_api_carries_position_and_machine_hours(
        client, admin_auth, world, session_factory):
    await _add(client, admin_auth, world, hours=1)      # Tool priced work: implements
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        change.status = "in_implementation"
        change.machine_class_id = world["big"]
        await s.commit()
    res = await client.post(_url(world, "/implementation/bookings"), json={
        "department_id": world["tool"], "hours": 2, "labour_position": "Toolmaker",
        "machine_hours": 1.5}, headers=admin_auth)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["labour_position"] == "Toolmaker" and body["machine_hours"] == 1.5
    assert body["machine_class_id"] == world["big"]


# ---------------------------------------------------------------- stale / tasks

async def test_review_task_for_finance_only(client, admin_auth, world, session_factory):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=world["org_id"], username="fin", email="fin@test.io",
                 full_name="Fin", role="engineer",
                 hashed_password=get_password_hash("fin-secret-12"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=world["fin"]))
        await s.commit()
    fin_auth = await login(client, "fin@test.io")
    # nothing published: due
    body = (await client.get("/api/v1/cost-sheet/review-task", headers=fin_auth)).json()
    assert body["due"] and body["is_finance"]
    # admin (not acting as Finance) gets no task
    body = (await client.get("/api/v1/cost-sheet/review-task", headers=admin_auth)).json()
    assert body["due"] is False and body["is_finance"] is False
    # a fresh version: not due; costing context carries the stale state
    # valid a few days back: the change (created now) is priced with it
    await _version(session_factory, world["org_id"], valid_from=date.today() - timedelta(days=3),
                   rates=[dict(department_id=world["tool"], hourly_rate=1, currency="USD")])
    async with session_factory() as s:
        v = (await s.execute(select(CostSheetVersion))).scalars().one()
        v.published_at = datetime.utcnow()
        await s.commit()
    body = (await client.get("/api/v1/cost-sheet/review-task", headers=fin_auth)).json()
    assert body["due"] is False
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["stale"]["stale"] is False and ctx["current_version"]["version"] == 1
    assert ctx["rate_source"] == "cost_sheet"


async def test_context_offers_no_labour_positions(client, admin_auth, world, session_factory):
    """One rate per department per plant (104): nothing to pick a position
    from any more; the key stays, empty, for older clients."""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=1, currency="USD"),
        dict(department_id=world["tool"], plant_id=world["home"],
             hourly_rate=1, currency="USD")])
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["positions_by_department"] == {}


# ---------------------------------------------------------------- pricing date

async def _created_on(session_factory, world, when: datetime):
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        change.created_at = when
        await s.commit()


async def test_change_priced_with_the_version_valid_on_its_creation_date(
        client, admin_auth, world, session_factory, monkeypatch):
    """An ECR is priced with the rates valid on the day it was CREATED, never
    the day a line is entered; later versions never move it."""
    monkeypatch.setenv("PLM_BUSINESS_TZ", "America/New_York")
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 3, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD"),
                          dict(department_id=world["qa"], hourly_rate=70, currency="USD")])
    # 03:00 UTC on 1 March is still 28 February in the business timezone
    await _created_on(session_factory, world, datetime(2026, 3, 1, 3, 0))
    line = await _add(client, admin_auth, world, hours=2)
    assert (line["rate"], line["cost_sheet_version"]) == (50, 1)
    assert line["rate_on"] == "2026-02-28"
    # Quality has no rate in v1 (the change's version): the gap is filled
    # from the earliest later version that has one, and the label says so
    qa = await _add(client, admin_auth, world, department_id=world["qa"], hours=1)
    assert (qa["rate"], qa["cost_sheet_version"]) == (70, 2)
    assert qa["rate_label"].endswith(
        "no rate in v1 on the creation date; taken from v2 valid from 1 Mar 2026")
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["current_version"]["version"] == 1 and ctx["pricing_date"] == "2026-02-28"
    summ = await _summation(session_factory, world)
    assert summ["cost_sheet_current_version"] == 1
    assert not any(w["code"] == "cost_sheet_outdated" for w in summ["warnings"])
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        assert await costing_rates.version_warning(s, change) is None
    # a version published later for later dates never re-prices it
    await _version(session_factory, world["org_id"], version=3, valid_from=date(2026, 5, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=99, currency="USD")])
    res = await client.put(_url(world, f"/costing/positions/{line['id']}"),
                           json={"hours": 3}, headers=admin_auth)
    assert (res.json()["rate"], res.json()["cost_sheet_version"]) == (50, 1)
    # a change created on 1 March (business time) takes v2
    await _created_on(session_factory, world, datetime(2026, 3, 1, 15, 0))
    res = await client.put(_url(world, f"/costing/positions/{line['id']}"),
                           json={"hours": 4}, headers=admin_auth)
    assert (res.json()["rate"], res.json()["cost_sheet_version"]) == (60, 2)


async def test_booking_basis_switch_prices_actuals_on_the_creation_date(
        world, session_factory, monkeypatch):
    """Actuals follow the booking date by default; one constant moves them to
    the change's creation date."""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 6, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 2, 1, 12))
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        change.status = "in_implementation"
        s.add(ImplementationBooking(change_id=change.id, department_id=world["tool"],
                                    hours=2, booked_by=world["admin_id"],
                                    booked_at=datetime(2026, 7, 1, 12)))
        await s.commit()
    assert costing_rates.BOOKING_PRICING_BASIS == "booking_date"
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        act = await PnlService.change_actuals(s, change)
        tool = next(d for d in act["departments"] if d["department_id"] == world["tool"])
        assert tool["actual_cost"] == 120
    monkeypatch.setattr(costing_rates, "BOOKING_PRICING_BASIS", "change_created")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        act = await PnlService.change_actuals(s, change)
        tool = next(d for d in act["departments"] if d["department_id"] == world["tool"])
        assert tool["actual_cost"] == 100


# ---------------------------------------------------------------- 098 data fix

async def test_098_creates_a_version_for_undated_department_rates(
        db_engine, session_factory, world):
    import importlib.util
    import pathlib
    import sys
    import types
    path = pathlib.Path(__file__).parents[1] / "alembic/versions/098_costing_rate_snapshot.py"
    spec = importlib.util.spec_from_file_location("m098", path)
    m = importlib.util.module_from_spec(spec)
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = types.SimpleNamespace(op=None)
    try:
        spec.loader.exec_module(m)
    finally:
        if saved is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = saved
    # The real table allows a NULL effective_from (the model says otherwise):
    # rebuild it that way, then two undated rows (the newer id wins).
    from sqlalchemy import text
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TABLE department_rate"))
        await conn.execute(text(
            "CREATE TABLE department_rate (id INTEGER PRIMARY KEY, department_id INTEGER,"
            " plant_id INTEGER, hourly_rate FLOAT, min_factor FLOAT, effective_from DATE)"))
        for rate in (60, 65):
            await conn.execute(text(
                "INSERT INTO department_rate (department_id, plant_id, hourly_rate,"
                " min_factor, effective_from) VALUES (:d, :p, :r, 1, NULL)"),
                {"d": world["tool"], "p": world["home"], "r": rate})
    async with db_engine.begin() as conn:
        await conn.run_sync(m._version_for_undated_orgs)
        await conn.run_sync(m._version_for_undated_orgs)       # idempotent
    async with session_factory() as s:
        vs = (await s.execute(select(CostSheetVersion))).scalars().all()
        assert len(vs) == 1
        v = vs[0]
        assert (v.version, v.status, v.valid_from) == (1, "published", date(2020, 1, 1))
        assert [(r.hourly_rate, r.currency) for r in v.rates] == [(65, "USD")]


async def test_gap_fill_takes_a_missing_rate_from_the_next_version_only(
        client, admin_auth, world, session_factory):
    """Department with an EMPTY rate in v1 but priced in v2 (and v3): priced
    from v2, the earliest later version, labelled. A department priced in v1
    and changed in v2 stays on v1. (A missing row: see the test above.)"""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD"),
        dict(department_id=world["qa"], hourly_rate=None, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 3, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD"),
                          dict(department_id=world["qa"], hourly_rate=70, currency="USD")])
    await _version(session_factory, world["org_id"], version=3, valid_from=date(2026, 4, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=61, currency="USD"),
                          dict(department_id=world["qa"], hourly_rate=71, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 2, 10, 15))
    tool = await _add(client, admin_auth, world, hours=2)
    assert (tool["rate"], tool["cost_sheet_version"]) == (50, 1)
    assert "taken from" not in tool["rate_label"]
    qa = await _add(client, admin_auth, world, department_id=world["qa"], hours=1)
    assert (qa["rate"], qa["cost_sheet_version"]) == (70, 2)
    assert "no rate in v1 on the creation date; taken from v2" in qa["rate_label"]
    async with session_factory() as s:
        p = await s.get(CostingPosition, qa["id"])
        # the snapshot records the version actually used, and why
        assert p.cost_sheet_version == 2 and p.rate_detail["gap_fill"]["no_rate_in"] == 1
        change = await s.get(ChangeRequest, world["change_id"])
        assert await costing_rates.version_warning(s, change) is None
    summ = await _summation(session_factory, world)
    assert summ["cost_sheet_current_version"] == 1
    assert not any(w["code"] == "cost_sheet_outdated" for w in summ["warnings"])


async def test_gap_fill_for_a_machine_class_rate(client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 3, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=50, currency="USD")],
                   machines=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  hourly_rate=85, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 2, 10, 15))
    m = await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=2,
                   machine_class_id=world["big"])
    assert (m["rate"], m["cost_sheet_version"], m["line_value"]) == (85, 2, 170)
    assert "no rate in v1 on the creation date; taken from v2" in m["rate_label"]


async def test_change_older_than_the_first_version_is_priced_with_it(
        client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], valid_from=date(2026, 3, 1), rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 5, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 1, 15, 15))
    line = await _add(client, admin_auth, world, hours=2)
    assert (line["rate"], line["cost_sheet_version"]) == (50, 1)
    assert line["rate_label"].endswith("priced with v1, the earliest cost sheet")
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["current_version"]["version"] == 1
    assert ctx["pricing_note"] == "priced with v1, the earliest cost sheet"
    summ = await _summation(session_factory, world)
    assert summ["cost_sheet_current_version"] == 1
    assert not any(w["code"] == "cost_sheet_outdated" for w in summ["warnings"])


async def test_old_line_without_currency_is_flagged(client, admin_auth, world, session_factory):
    """A line from before 098 has no currency: read in the costing plant's
    currency and said so, never silently."""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    line = await _add(client, admin_auth, world, kind="external", pricing="estimate",
                      est_cost=100)
    async with session_factory() as s:
        p = await s.get(CostingPosition, line["id"])
        p.currency = None
        await s.commit()
    summ = await _summation(session_factory, world)
    w = next(w for w in summ["warnings"] if w["code"] == "currency_unrecorded")
    assert "read as USD, the costing plant's currency" in w["message"]
    assert w["message"].startswith("1 costing line has")


async def test_hours_only_line_without_currency_is_not_flagged(
        client, admin_auth, world, session_factory):
    """Hours are priced at the rate, in the rate's own currency: a line
    without a money amount has nothing read in the plant's currency."""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    line = await _add(client, admin_auth, world, hours=2)
    async with session_factory() as s:
        p = await s.get(CostingPosition, line["id"])
        p.currency = None
        await s.commit()
    summ = await _summation(session_factory, world)
    assert not any(w["code"] == "currency_unrecorded" for w in summ["warnings"])


async def test_backdated_version_after_a_gap_fill_shows_the_outdated_warning(
        client, admin_auth, world, session_factory):
    """Quality was gap filled from v2 because v1 (the change's version) had
    no rate. A v3 published later, backdated over the creation date, with a
    Quality rate is now the change's version: the v2 line is outdated."""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 3, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD"),
                          dict(department_id=world["qa"], hourly_rate=70, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 2, 10, 15))
    qa = await _add(client, admin_auth, world, department_id=world["qa"], hours=1)
    assert (qa["rate"], qa["cost_sheet_version"]) == (70, 2)
    summ = await _summation(session_factory, world)
    assert summ["cost_sheet_versions_used"] == []
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        assert await costing_rates.version_warning(s, change) is None
    await _version(session_factory, world["org_id"], version=3, valid_from=date(2026, 2, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=50, currency="USD"),
                          dict(department_id=world["qa"], hourly_rate=65, currency="USD")])
    summ = await _summation(session_factory, world)
    assert summ["cost_sheet_current_version"] == 3
    assert summ["cost_sheet_versions_used"] == [2]
    outdated = costing_rates.outdated_message([2], 3)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        assert await costing_rates.version_warning(s, change) == outdated


async def test_cost_line_gap_fill_only_from_the_version_the_rule_picks(
        world, session_factory):
    """A cost line counts as gap filled only when the change's version has
    no rate AND the line's version is the earliest later one with a rate."""
    ids = {}
    ids[1] = await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    for n, vf in ((2, date(2026, 3, 1)), (3, date(2026, 4, 1))):
        ids[n] = await _version(session_factory, world["org_id"], version=n, valid_from=vf,
                                rates=[dict(department_id=world["qa"], hourly_rate=70 + n,
                                            currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 2, 10, 15))
    async with session_factory() as s:
        for n in (2, 3):
            s.add(AssessmentCostLine(
                assessment_id=world["assessments"]["Quality"], plant_id=world["home"],
                demand_hours=1, internal_cost=70 + n, currency="USD",
                cost_sheet_version_id=ids[n], rate_source="cost_sheet"))
        await s.commit()
        change = await s.get(ChangeRequest, world["change_id"])
        book = costing_rates.RateBook(s)
        current, _ = await book.pricing_version(world["org_id"], date(2026, 2, 10))
        chain = await book.chain(world["org_id"])
        filled = costing_rates.cost_line_gap_filled
        assert filled(current, ids[2], world["qa"], world["home"], chain)
        # v3 has a rate too, but the gap fill takes v2: v3 is not the rule
        assert not filled(current, ids[3], world["qa"], world["home"], chain)
        # the change's version has a Tool rate: never a gap fill
        assert not filled(current, ids[2], world["tool"], world["home"], chain)
        assert await costing_rates.costing_versions(s, change) == [3]
        assert await costing_rates.version_warning(s, change) \
            == costing_rates.outdated_message([3], 1)
    summ = await _summation(session_factory, world)
    assert summ["cost_sheet_versions_used"] == [3]


async def test_sampling_fills_only_the_missing_labour_rate(
        client, admin_auth, world, session_factory):
    """v1 has the sampling row and the machine rate but no Quality labour
    rate: the row's hours, handling and v1's machine rate stay, only the
    labour rate comes from v2 (which changed the row and the press rate)."""
    await _version(session_factory, world["org_id"],
                   rates=[dict(department_id=world["tool"], hourly_rate=50, currency="USD")],
                   machines=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  hourly_rate=85, currency="USD")],
                   sampling=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  mode="components", setup_hours=1, run_hours_default=2,
                                  labour_hours=2, labour_department_id=world["qa"],
                                  handling_cost=10, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 3, 1),
                   rates=[dict(department_id=world["qa"], hourly_rate=70, currency="USD")],
                   machines=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  hourly_rate=100, currency="USD")],
                   sampling=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  mode="components", setup_hours=5, run_hours_default=5,
                                  labour_hours=4, labour_department_id=world["qa"],
                                  handling_cost=99, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 2, 10, 15))
    sp = await _add(client, admin_auth, world, kind="sampling", label="T1", trials=1,
                    machine_class_id=world["big"])
    # (1 + 2) h x 85 + 2 h x 70 + 10 handling, on v1's row
    assert (sp["rate"], sp["cost_sheet_version"], sp["line_value"]) == (405, 1, 405)
    assert sp["rate_label"].endswith(
        "no labour rate in v1 on the creation date; labour rate taken from v2 "
        "valid from 1 Mar 2026")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        assert await costing_rates.version_warning(s, change) is None


async def test_plant_row_of_the_creation_date_version_beats_a_later_all_plants_row(
        client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], plant_id=world["home"], hourly_rate=50,
             currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 3, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 2, 10, 15))
    line = await _add(client, admin_auth, world, hours=1)
    assert (line["rate"], line["cost_sheet_version"]) == (50, 1)
    assert "taken from" not in line["rate_label"]


async def test_all_plants_row_of_the_creation_date_version_beats_a_later_plant_row(
        client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 3, 1),
                   rates=[dict(department_id=world["tool"], plant_id=world["home"],
                               hourly_rate=60, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 2, 10, 15))
    line = await _add(client, admin_auth, world, hours=1)
    assert (line["rate"], line["cost_sheet_version"]) == (50, 1)
    assert "taken from" not in line["rate_label"]


async def test_gap_fill_label_for_a_change_older_than_the_first_version(
        client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], valid_from=date(2026, 3, 1), rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 5, 1),
                   rates=[dict(department_id=world["qa"], hourly_rate=70, currency="USD")])
    await _created_on(session_factory, world, datetime(2026, 1, 15, 15))
    qa = await _add(client, admin_auth, world, department_id=world["qa"], hours=1)
    assert qa["rate_label"].endswith(
        "no rate in v1, the earliest cost sheet; taken from v2 valid from 1 May 2026")


async def test_unpriced_machine_lines_name_the_class_rate_not_the_department(
        client, admin_auth, world, session_factory):
    """A machine_time line without a rate misses the class's machine rate at
    the plant, not the department's labour rate: said so, with the hours;
    sampling the same way."""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    async with session_factory() as s:
        plant = (await s.get(Plant, world["home"])).name
    await _add(client, admin_auth, world, hours=2)
    for h in (5, 7):
        await _add(client, admin_auth, world, kind="machine_time", label="Press", hours=h,
                   machine_class_id=world["big"])
    await _add(client, admin_auth, world, kind="sampling", label="T1", trials=2,
               machine_class_id=world["big"])
    machine = f"No machine rate for class 200-450 t at {plant}: 12 h unpriced"
    sampling = f"No sampling rate for class 200-450 t at {plant}: 2 trials unpriced"
    summ = await _summation(session_factory, world)
    named = [(w["message"], w.get("department_id"), w.get("subject"))
             for w in summ["warnings"] if w["code"] == "no_rate_department"]
    assert named == [(machine, None, f"machine rate for class 200-450 t at {plant}"),
                     (sampling, None, f"sampling rate for class 200-450 t at {plant}")]
    assert not any("No cost sheet rate for Tool Engineer" in w["message"]
                   for w in summ["warnings"])
    assert {u["subject"] for u in summ["unpriced_lines"]} == {
        f"machine rate for class 200-450 t at {plant}",
        f"sampling rate for class 200-450 t at {plant}"}
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        got = await costing_rates.unpriced_departments(s, change)
    assert [(u["message"], u["count"]) for u in got] == [(machine, 2), (sampling, 1)]
    # the API carries them for the change header
    res = await client.get(_url(world), headers=admin_auth)
    assert [u["message"] for u in res.json()["costing_unpriced"]] == [machine, sampling]
