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
        dict(department_id=world["tool"], hourly_rate=20, currency="USD"),
        dict(department_id=world["tool"], position="Engineer", plant_id=world["home"],
             hourly_rate=20, currency="USD")],
        overheads=[dict(kind="percent", value=7.5)])
    line = await _add(client, admin_auth, world, hours=5, labour_position="Engineer")
    assert line["rate"] == 21.5 and line["currency"] == "USD"
    assert line["cost_sheet_version_id"] == vid and line["cost_sheet_version"] == 1
    assert line["rate_source"] == "cost_sheet" and line["rate_is_snapshot"]
    assert line["rate_label"] == "Cost sheet v1, Tool Engineer, Engineer, 21.50 USD/h"
    assert line["line_value"] == 107.5 and line["rate_missing"] is False
    assert line["rate_match"] == "department+position+plant"

    summ = await _summation(session_factory, world)
    assert summ["currency"] == "USD"
    assert summ["totals"]["one_time_internal"] == 107.5
    assert summ["cost_sheet_versions_used"] == [1]
    assert summ["warnings"] == [] and summ["unpriced_lines"] == []

    # Finance publishes v2: the costed line keeps its snapshot ...
    await _version(session_factory, world["org_id"], version=2,
                   valid_from=date(2026, 2, 1), rates=[
                       dict(department_id=world["tool"], position="Engineer",
                            hourly_rate=30, currency="USD")])
    summ = await _summation(session_factory, world)
    assert summ["totals"]["one_time_internal"] == 107.5
    assert summ["cost_sheet_current_version"] == 2
    # ... a label edit does not re-price it ...
    res = await client.put(_url(world, f"/costing/positions/{line['id']}"),
                           json={"label": "Renamed"}, headers=admin_auth)
    assert res.json()["cost_sheet_version"] == 1
    # ... changing the hours does, from the version valid today
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
        assert msgs == ["Costing used cost sheet v1, current is v2"]
        assert not any(w["code"] == "currency_mismatch" for w in out["warnings"])
        pnl = await PnlService.offer_vs_actual(s, change)
        assert "Costing used cost sheet v1, current is v2" in pnl["warnings"]
        assert pnl["costing_currency"] == "USD"


# ---------------------------------------------------------------- P&L actuals

async def test_actuals_priced_on_the_booking_date(client, admin_auth, world,
                                                  session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD"),
        dict(department_id=world["tool"], position="Toolmaker", hourly_rate=40,
             currency="USD")],
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
            # v1 period, position rate + machine hours: 1 h x 40 + 2 mh x 80
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
        assert tool["actual_cost"] == 100 + 40 + 160 + 60
        assert tool["machine_hours"] == 2 and tool["machine_cost"] == 160
        assert tool["rates"] == [40, 50, 60] and tool["hourly_rate"] is None
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
    await _version(session_factory, world["org_id"], valid_from=date.today(),
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


async def test_context_lists_positions_with_rates(client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], position="Engineer", hourly_rate=1, currency="USD"),
        dict(department_id=world["tool"], position="Technician", plant_id=world["home"],
             hourly_rate=1, currency="USD"),
        dict(department_id=world["tool"], position="Other plant", plant_id=world["eur"],
             hourly_rate=1, currency="EUR")])
    ctx = (await client.get(_url(world, "/costing/context"), headers=admin_auth)).json()
    assert ctx["positions_by_department"][str(world["tool"])] == ["Engineer", "Technician"]


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
