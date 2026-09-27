"""Review fixes to cost sheet phase 2 (165b0afc):

- a line that found no rate keeps no snapshot and is priced live, and an
  update re-prices it;
- lines priced on the change's machine class keep machine_class_id None and
  follow the class when it moves; the class moves only in costing (admins
  exempt), audited;
- the rate's currency is stored apart from the money's;
- seeded grid lines without a rate say None, not 0; saving the grid does not
  re-price lines nobody touched;
- effort by department is filled from the standing internal_effort lines;
- P&L rows carry their currency, no margin across currencies, the summary is
  grouped by currency, no_rate is flagged, and the list costs a fixed number
  of queries whatever the number of changes;
- 098's data step dates the migrated version from the org's earliest rate.
"""
from datetime import date, datetime

import pytest
from sqlalchemy import event, select

from app.models.change import (
    ChangeAssessment, ChangeChangelog, ChangeImpactedItem, ChangeRequest,
)
from app.models.change_cost import AssessmentCostLine, CostingPosition
from app.models.change_impl import ImplementationBooking
from app.models.change_offer import ChangeOffer
from app.models.cost_sheet import CostSheetVersion
from app.models.entities import User
from app.models.part import Part
from app.services.cost_service import CostService
from app.services.offer_service import default_data
from app.services.pnl_service import PnlService
from tests.test_costing_cost_sheet import (  # noqa: F401
    _add, _summation, _url, _version, world,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- P2-2

async def test_no_rate_keeps_no_snapshot_and_update_reprices(
        client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    line = await _add(client, admin_auth, world, department_id=world["qa"], hours=4)
    assert line["rate"] is None and line["rate_on"] is None
    assert line["rate_is_snapshot"] is False and line["rate_missing"]
    # Finance adds the rate in a new version: the line is priced live ...
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 2, 1),
                   rates=[dict(department_id=world["qa"], hourly_rate=30, currency="USD")])
    summ = await _summation(session_factory, world)
    assert summ["totals"]["one_time_internal"] == 120 and summ["unpriced_lines"] == []
    # ... and any update (even a label) takes the snapshot now
    res = await client.put(_url(world, f"/costing/positions/{line['id']}"),
                           json={"label": "Renamed"}, headers=admin_auth)
    body = res.json()
    assert body["rate"] == 30 and body["cost_sheet_version"] == 2
    assert body["rate_is_snapshot"] and body["rate_on"] is not None


# ---------------------------------------------------------------- P2-3

async def _machine_world(session_factory, world):
    await _version(session_factory, world["org_id"],
                   rates=[dict(department_id=world["tool"], hourly_rate=50, currency="USD")],
                   machines=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  hourly_rate=85, currency="USD"),
                             dict(machine_class="<=200 t", machine_class_id=world["small"],
                                  hourly_rate=40, currency="USD")])


async def test_machine_class_change_reprices_lines_without_their_own(
        client, admin_auth, world, session_factory):
    await _machine_world(session_factory, world)
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["big"]}, headers=admin_auth)
    assert res.status_code == 200
    follows = await _add(client, admin_auth, world, kind="machine_time", label="P", hours=2)
    own = await _add(client, admin_auth, world, kind="machine_time", label="Q", hours=2,
                     machine_class_id=world["big"])
    assert follows["machine_class_id"] is None and follows["rate"] == 85
    assert follows["machine_class_used_id"] == world["big"]
    assert follows["machine_class"] == "200-450 t" and follows["machine_class_from_change"]
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["small"]}, headers=admin_auth)
    assert res.status_code == 200
    async with session_factory() as s:
        f = await s.get(CostingPosition, follows["id"])
        o = await s.get(CostingPosition, own["id"])
        assert f.rate == 40 and f.machine_class_id is None
        assert f.rate_detail["machine_class_id"] == world["small"]
        assert o.rate == 85 and o.machine_class_id == world["big"]
        log = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == world["change_id"],
            ChangeChangelog.action == "machine_class_set"))).scalars().all()
        assert "1 line(s) re-priced" in log[-1].action_description


async def test_machine_class_only_while_costing_admin_exempt(
        client, admin_auth, world, session_factory):
    from app.services import costing_rates
    await _machine_world(session_factory, world)
    async with session_factory() as s:
        (await s.get(ChangeRequest, world["change_id"])).status = "quoting"
        await s.commit()
    res = await client.put(_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["big"]}, headers=admin_auth)
    assert res.status_code == 200          # admin: an audited correction
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        eng = (await s.execute(select(User).where(User.email == "eng@test.io"))).scalar_one()
        assert costing_rates.machine_class_open(change, eng) is False
        assert await costing_rates.may_set_machine_class(s, change, eng) is False
        with pytest.raises(costing_rates.MachineClassLocked):
            await costing_rates.set_machine_class(s, change, world["small"], eng)


# ---------------------------------------------------------------- P3 currencies

async def test_rate_currency_is_stored_apart_from_the_money_currency(
        client, admin_auth, world, session_factory):
    # the plant is USD, Finance states this rate in EUR
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="EUR")])
    line = await _add(client, admin_auth, world, hours=2)
    assert line["rate_currency"] == "EUR" and line["currency"] == "USD"
    async with session_factory() as s:
        p = await s.get(CostingPosition, line["id"])
        assert (p.rate_currency, p.currency) == ("EUR", "USD")
    summ = await _summation(session_factory, world)
    assert summ["totals_by_currency"]["EUR"]["one_time_internal"] == 100
    assert summ["totals"]["one_time_internal"] == 0 and summ["mixed_currency"]


# ---------------------------------------------------------------- P3 grid lines

async def test_seeded_line_without_rate_is_none_not_zero(world, session_factory):
    import json
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        a = await s.get(ChangeAssessment, world["assessments"]["Quality"])
        a.details = json.dumps({"impacts": [{"key": "drawing", "impacted": True}]})
        await s.flush()
        # a published sheet without a Quality rate
        await s.commit()
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        a = await s.get(ChangeAssessment, world["assessments"]["Quality"])
        seeded = await CostService.seed_from_checklist(s, change, a, world["admin_id"])
        await s.commit()
        assert len(seeded) == 1
        line = seeded[0]
        assert line.rate_snapshot is None and line.rate_source is None
        assert line.cost_sheet_version_id is None and line.internal_cost == 0


async def test_grid_save_does_not_reprice_unchanged_lines(
        client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    url = _url(world, f"/assessments/{world['assessments']['Tool Engineer']}/cost-lines")
    keep = {"plant_id": world["home"], "activity_label": "Rework",
            "cost_kind": "one_time", "demand_hours": 2}
    move = {"plant_id": world["home"], "activity_label": "Drawing",
            "cost_kind": "one_time", "demand_hours": 1}
    res = await client.put(url, json={"lines": [keep, move]}, headers=admin_auth)
    assert res.status_code in (200, 201), res.text
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 2, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=70, currency="USD")])
    res = await client.put(url, json={"lines": [keep, {**move, "demand_hours": 3}]},
                           headers=admin_auth)
    assert res.status_code in (200, 201), res.text
    by_label = {l["activity_label"]: l for l in res.json()}
    assert by_label["Rework"]["rate_snapshot"] == 50           # untouched: v1 kept
    assert by_label["Drawing"]["rate_snapshot"] == 70          # changed: re-priced
    assert by_label["Drawing"]["internal_cost"] == 210


# ---------------------------------------------------------------- cosmetics

async def test_effort_by_department_from_internal_effort_lines(
        client, admin_auth, world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=24, currency="USD")])
    await _add(client, admin_auth, world, kind="internal_effort", label="Assessment", hours=6)
    await _add(client, admin_auth, world, hours=5)
    summ = await _summation(session_factory, world)
    assert summ["effort_by_department"] == [
        {"department_id": world["tool"], "effort_hours": 6.0}]
    assert summ["total_effort_hours"] == 6.0


async def test_position_totals_are_not_counted_twice(
        client, admin_auth, world, session_factory):
    """CR-3's shape: the grand total already holds the positions, internal
    hours and external money alike."""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=21.5, currency="USD")])
    await _add(client, admin_auth, world, hours=13)                           # 279.50
    await _add(client, admin_auth, world, kind="external", label="Tool insert",
               est_cost=13350)
    summ = await _summation(session_factory, world)
    assert summ["totals"]["grand_total"] == 13629.5
    assert summ["total_position_cost"] + summ["total_position_hours_cost"] == 13629.5
    dep = next(r for r in summ["by_department"] if r["department_id"] == world["tool"])
    assert dep["one_time_internal"] + dep["one_time_external"] == 13629.5


# ---------------------------------------------------------------- P&L

async def _pnl_change(s, world, n, status="in_implementation", **values):
    c = ChangeRequest(change_number=f"C-PNL-{n}", title=f"pnl {n}", reason="r",
                      change_type="physical_part", project_id=world["project_id"],
                      raised_by=world["admin_id"], lead_id=world["admin_id"],
                      status=status, customer_relevant=True, **values)
    s.add(c)
    await s.flush()
    a = ChangeAssessment(change_id=c.id, department_id=world["tool"], stage_order=1,
                         verdict="feasible")
    s.add(a)
    await s.flush()
    s.add(AssessmentCostLine(assessment_id=a.id, plant_id=world["home"],
                             activity_label="x", cost_kind="one_time", demand_hours=1,
                             rate_snapshot=50, internal_cost=50, external_cost=0,
                             currency="USD"))
    s.add(CostingPosition(change_id=c.id, department_id=world["tool"], label="own",
                          kind="own_time", pricing="estimate", hours=2,
                          created_by=world["admin_id"]))
    s.add(ImplementationBooking(change_id=c.id, department_id=world["tool"], hours=1,
                                booked_by=world["admin_id"],
                                booked_at=datetime(2026, 3, 1, 12)))
    return c


async def test_pnl_rows_carry_currency_and_no_margin_across_currencies(
        world, session_factory):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    async with session_factory() as s:
        same = await _pnl_change(s, world, 1, status="quoting", quoted_price=1000)
        other = await _pnl_change(s, world, 2, status="quoted", quoted_price=1000)
        s.add(ChangeOffer(change_id=other.id, version=1, status="sent", currency="EUR",
                          total_one_time=1000, data=default_data(),
                          created_by=world["admin_id"]))
        norate = await _pnl_change(s, world, 3, status="quoting", quoted_price=500)
        s.add(CostingPosition(change_id=norate.id, department_id=world["qa"], label="qa",
                              kind="own_time", pricing="estimate", hours=3,
                              created_by=world["admin_id"]))
        await s.commit()
        admin = await s.get(User, world["admin_id"])
        rows = {r["change_number"]: r for r in await PnlService.changes_pnl(s, admin)}
        summary = await PnlService.summary(s, admin)
    a = rows["C-PNL-1"]
    assert a["currency"] == "USD" and a["revenue_currency"] == "USD"
    # the row's cost is the summation's: the 50 cost line plus the costing
    # position (2 h x 50), not the cost line alone
    assert a["internal_cost"] == 150 and a["total_cost"] == 150
    assert a["margin"] == 850 and a["planned_margin"] is not None
    assert "position_cost" not in a
    b = rows["C-PNL-2"]
    assert b["revenue_currency"] == "EUR" and b["currency_mismatch"]
    assert b["margin"] is None and b["margin_pct"] is None and b["planned_margin"] is None
    assert any(w["code"] == "currency_mismatch" for w in b["warnings"])
    c = rows["C-PNL-3"]
    assert c["no_rate"] and any(w["code"] == "no_rate" for w in c["warnings"])
    assert summary["currency"] == "USD" and summary["currencies"] == ["USD"]
    usd = summary["by_currency"]["USD"]["totals"]
    assert usd["mismatch_count"] == 1 and usd["no_rate_count"] == 1
    # the EUR revenue is in no USD sum
    assert usd["revenue"] == 1500
    # every row counts its positions; C-PNL-3's 3 QA hours have no rate
    assert usd["total_cost"] == 3 * 150


async def test_pnl_list_costs_a_fixed_number_of_queries(
        world, session_factory, db_engine):
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    await _version(session_factory, world["org_id"], version=2, valid_from=date(2026, 6, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD")])

    await _version(session_factory, world["org_id"], version=3, valid_from=date(2026, 7, 1),
                   rates=[dict(department_id=world["tool"], hourly_rate=60, currency="USD")],
                   machines=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  hourly_rate=85, currency="USD")],
                   sampling=[dict(machine_class="200-450 t", machine_class_id=world["big"],
                                  mode="flat", flat_price=1250, currency="USD")])

    async def count_for(n_changes: int, start: int) -> int:
        async with session_factory() as s:
            for i in range(n_changes):
                c = await _pnl_change(s, world, start + i, quoted_price=1000)
                # machine and sampling lines without a class of their own,
                # priced live on the tonnage default of the impacted tool,
                # and a booking with machine hours
                tool = Part(part_number=f"T-Q-{start + i}", name="Tool",
                            item_category="tool", part_type="tool",
                            tool_tonnage_class=350, project_id=world["project_id"],
                            created_by=world["admin_id"])
                s.add(tool)
                await s.flush()
                s.add(ChangeImpactedItem(change_id=c.id, part_id=tool.id,
                                         created_by=world["admin_id"]))
                s.add(CostingPosition(change_id=c.id, department_id=world["tool"],
                                      label="press", kind="machine_time",
                                      pricing="estimate", hours=3,
                                      created_by=world["admin_id"]))
                s.add(CostingPosition(change_id=c.id, department_id=world["tool"],
                                      label="T1", kind="sampling", pricing="estimate",
                                      trials=2, created_by=world["admin_id"]))
                s.add(ImplementationBooking(change_id=c.id, department_id=world["tool"],
                                            hours=2, machine_hours=4,
                                            booked_by=world["admin_id"],
                                            booked_at=datetime(2026, 7, 15, 12)))
            await s.commit()
        async with session_factory() as s:
            admin = await s.get(User, world["admin_id"])
            seen = []

            def on_exec(conn, cursor, statement, *args):
                seen.append(statement)
            event.listen(db_engine.sync_engine, "before_cursor_execute", on_exec)
            try:
                rows = await PnlService.changes_pnl(s, admin)
            finally:
                event.remove(db_engine.sync_engine, "before_cursor_execute", on_exec)
            assert len(rows) >= n_changes
            # the machine, sampling and booked machine money is really in
            # (not skipped): 3 h x 85 + 2 x 1250 in the plan
            r = next(r for r in rows if r["change_number"] == f"C-PNL-{start}")
            assert r["internal_cost"] == 50 + 2 * 60 + 255 + 2500
            assert r["actual_cost"] is not None
            return len(seen)

    one = await count_for(1, 10)
    many = await count_for(6, 20)          # 7 changes in the list now
    assert many == one, f"{one} queries for 1 change, {many} for 7"


async def test_offer_vs_actual_eur_offer_on_usd_costing_has_no_margin(
        world, session_factory):
    """CR-3-like: the offer is in EUR, the costing (plant) in USD. The card
    shows each line in its own currency and no margin, like the list."""
    await _version(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=50, currency="USD")])
    async with session_factory() as s:
        c = await _pnl_change(s, world, 30, status="in_implementation", quoted_price=3000)
        s.add(ChangeOffer(change_id=c.id, version=1, status="sent", currency="EUR",
                          total_one_time=3000, data=default_data(),
                          created_by=world["admin_id"]))
        same = await _pnl_change(s, world, 31, status="in_implementation", quoted_price=3000)
        s.add(ChangeOffer(change_id=same.id, version=1, status="sent", currency="USD",
                          total_one_time=3000, data=default_data(),
                          created_by=world["admin_id"]))
        await s.commit()
        ova = await PnlService.offer_vs_actual(s, await s.get(ChangeRequest, c.id))
        ok = await PnlService.offer_vs_actual(s, await s.get(ChangeRequest, same.id))
        summ = await CostService.summation(s, await s.get(ChangeRequest, c.id))
    assert ova["currency"] == "EUR" and ova["revenue_currency"] == "EUR"
    assert ova["costing_currency"] == "USD" and ova["currency_mismatch"] is True
    for k in ("planned_margin", "actual_margin", "forecast_margin",
              "planned_margin_pct", "actual_margin_pct", "forecast_margin_pct",
              "variance"):
        assert ova[k] is None, k
    assert set(ova["margin_row"].values()) == {None}
    lines = {l["key"]: l for l in ova["lines"]}
    assert lines["revenue"]["currency"] == "EUR" and lines["revenue"]["planned"] == 3000
    assert lines["internal"]["currency"] == "USD" and lines["external"]["currency"] == "USD"
    # a line's own variance stays: it is within one currency
    assert lines["internal"]["variance"] is not None
    assert any("revenue is in EUR, the costing in USD" in w for w in ova["warnings"])
    # the /pnl list agrees
    assert summ["currency"] == "USD" and summ["revenue_currency"] == "EUR"
    # same currency: margins as before
    assert ok["currency_mismatch"] is False and ok["planned_margin"] is not None
    assert ok["margin_row"]["planned"] == ok["planned_margin"]
    assert {l["currency"] for l in ok["lines"]} == {"USD"}


# ---------------------------------------------------------------- 098

async def test_098_version_valid_from_the_orgs_earliest_rate(db_engine, session_factory, world):
    import importlib.util
    import pathlib
    import sys
    import types
    from sqlalchemy import text
    path = pathlib.Path(__file__).parents[1] / "alembic/versions/098_costing_rate_snapshot.py"
    spec = importlib.util.spec_from_file_location("m098b", path)
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
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TABLE department_rate"))
        await conn.execute(text(
            "CREATE TABLE department_rate (id INTEGER PRIMARY KEY, department_id INTEGER,"
            " plant_id INTEGER, hourly_rate FLOAT, min_factor FLOAT, effective_from DATE)"))
        # the old Tool rate is superseded; Quality's single rate is newer
        for dept, rate, since in ((world["tool"], 55, "2024-01-01"),
                                  (world["tool"], 60, "2025-06-01"),
                                  (world["qa"], 40, "2025-01-01")):
            await conn.execute(text(
                "INSERT INTO department_rate (department_id, plant_id, hourly_rate,"
                " min_factor, effective_from) VALUES (:d, :p, :r, 1, :f)"),
                {"d": dept, "p": world["home"], "r": rate, "f": since})
    async with db_engine.begin() as conn:
        await conn.run_sync(m._version_for_undated_orgs)
    async with session_factory() as s:
        v = (await s.execute(select(CostSheetVersion))).scalars().one()
        assert v.valid_from == date(2024, 1, 1)
        assert sorted(r.hourly_rate for r in v.rates) == [40, 60]
