"""Cost sheet (spec §15 / §15a): versions and validity chain, rights
(Finance or admin, acts-as aware), most-specific rate lookup, overheads,
machine and sampling prices, stale check, diff, export and the legacy
/changes/reference/rates shape."""
import io
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.acts_as import HEADER
from app.models.change_cost import DepartmentRate
from app.models.cost_sheet import (
    CostSheetMachineClass, CostSheetOverhead, CostSheetRate, CostSheetVersion,
    CostSheetMachineRate, CostSheetSamplingRate,
)
from app.models.entities import Plant
from app.models.workflow import Department, UserDepartment
from app.services import cost_sheet_service as svc

pytestmark = pytest.mark.asyncio
API = "/api/v1/cost-sheet"


@pytest.fixture
async def world(session_factory, seed):
    async with session_factory() as s:
        fin = Department(name="Finance", flow_type="info")
        tool = Department(name="Tooling-CS", flow_type="action")
        qa = Department(name="Quality-CS", flow_type="action")
        s.add_all([fin, tool, qa])
        await s.flush()
        p1 = (await s.execute(select(Plant))).scalars().first()
        p2 = Plant(organization_id=seed["org_id"], name="Second", code="p2", is_active=True)
        s.add(p2)
        await s.commit()
        return {**seed, "fin": fin.id, "tool": tool.id, "qa": qa.id,
                "p1": p1.id, "p2": p2.id}


async def _published(session_factory, org_id, *, version=1, valid_from=date(2026, 1, 1),
                     rates=(), overheads=(), machines=(), sampling=(),
                     published_at=None):
    async with session_factory() as s:
        v = CostSheetVersion(organization_id=org_id, version=version, status="published",
                             valid_from=valid_from,
                             published_at=published_at or datetime(2026, 1, 1))
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


async def _load(session_factory, vid):
    async with session_factory() as s:
        return await s.get(CostSheetVersion, vid)


# ---------------------------------------------------------------- lookups

async def test_rate_for_most_specific_match(session_factory, world):
    t, p1, p2 = world["tool"], world["p1"], world["p2"]
    await _published(session_factory, world["org_id"], rates=[
        dict(department_id=t, hourly_rate=50),
        dict(department_id=t, plant_id=p1, hourly_rate=55),
        dict(department_id=t, position="Engineer", hourly_rate=70),
        dict(department_id=t, position="Engineer", plant_id=p1, hourly_rate=75),
    ])
    async with session_factory() as s:
        org = world["org_id"]
        hit = await svc.rate_for(s, org, t, "engineer", p1, date(2026, 5, 1))
        assert (hit.rate, hit.match) == (75, "department+position+plant")
        hit = await svc.rate_for(s, org, t, "Engineer", p2, date(2026, 5, 1))
        assert (hit.rate, hit.match) == (70, "department+position")
        hit = await svc.rate_for(s, org, t, "Toolmaker", p1, date(2026, 5, 1))
        assert (hit.rate, hit.match) == (55, "department+plant")
        hit = await svc.rate_for(s, org, t, None, p2, date(2026, 5, 1))
        assert (hit.rate, hit.match) == (50, "department")
        assert hit.version == 1
        assert await svc.rate_for(s, org, world["qa"], None, p1) is None
        # before the first version there is no rate at all
        assert await svc.rate_for(s, org, t, None, p1, date(2025, 12, 31)) is None


async def test_rate_uses_the_version_valid_on_the_date(session_factory, world):
    t = world["tool"]
    await _published(session_factory, world["org_id"], rates=[
        dict(department_id=t, hourly_rate=50)])
    await _published(session_factory, world["org_id"], version=2,
                     valid_from=date(2026, 7, 1),
                     rates=[dict(department_id=t, hourly_rate=60)])
    async with session_factory() as s:
        assert (await svc.rate_for(s, world["org_id"], t, on_date=date(2026, 6, 30))).rate == 50
        assert (await svc.rate_for(s, world["org_id"], t, on_date=date(2026, 7, 1))).rate == 60
        versions = await svc.list_versions(s, world["org_id"])
        valid = svc.validity(versions)
        assert valid[versions[0].id] == (date(2026, 1, 1), date(2026, 6, 30))
        assert valid[versions[1].id] == (date(2026, 7, 1), None)


async def test_effective_labour_rate_with_most_specific_overhead(session_factory, world):
    t, q, p1, p2 = world["tool"], world["qa"], world["p1"], world["p2"]
    await _published(session_factory, world["org_id"], rates=[
        dict(department_id=t, hourly_rate=100), dict(department_id=q, hourly_rate=100)],
        overheads=[
            dict(kind="percent", value=10),                           # org
            dict(plant_id=p2, kind="percent", value=20),              # plant
            dict(department_id=t, kind="per_hour", value=5),          # dept
            dict(department_id=t, plant_id=p2, kind="percent", value=50),  # dept+plant
        ])
    async with session_factory() as s:
        org = world["org_id"]
        assert (await svc.effective_labour_rate(s, org, t, None, p2)).rate == 150
        assert (await svc.effective_labour_rate(s, org, t, None, p1)).rate == 105
        assert (await svc.effective_labour_rate(s, org, q, None, p2)).rate == 120
        hit = await svc.effective_labour_rate(s, org, q, None, p1)
        assert (hit.rate, hit.base_rate, hit.overhead["kind"]) == (110, 100, "percent")


async def test_machine_rate_by_class_ref_and_plant(session_factory, world):
    p1, p2 = world["p1"], world["p2"]
    await _published(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], hourly_rate=1)], machines=[
        dict(machine_class="200-450 t", hourly_rate=80),
        dict(machine_class="200-450 t", plant_id=p1, hourly_rate=90),
        dict(machine_class="200-450 t", machine_ref="Engel 350", hourly_rate=95),
    ])
    async with session_factory() as s:
        org = world["org_id"]
        assert (await svc.machine_rate_for(s, org, "200-450 t", p1)).rate == 90
        assert (await svc.machine_rate_for(s, org, "200-450 T", p2)).rate == 80
        assert (await svc.machine_rate_for(s, org, "200-450 t", p1,
                                           machine_ref="engel 350")).rate == 95
        assert (await svc.machine_rate_for(s, org, "200-450 t", p1,
                                           machine_ref="Other")).rate == 90
        assert await svc.machine_rate_for(s, org, ">800 t", p1) is None


async def test_sampling_flat_and_components(session_factory, world):
    t, p1 = world["tool"], world["p1"]
    await _published(session_factory, world["org_id"],
                     rates=[dict(department_id=t, position="Technician", hourly_rate=40)],
                     overheads=[dict(kind="percent", value=25)],
                     machines=[dict(machine_class="<=200 t", hourly_rate=60)],
                     sampling=[
                         dict(machine_class="<=200 t", mode="components", setup_hours=2,
                              run_hours_default=3, labour_hours=4, labour_department_id=t,
                              labour_position="Technician", handling_cost=100),
                         dict(machine_class=">800 t", mode="flat", flat_price=2500),
                     ])
    async with session_factory() as s:
        org = world["org_id"]
        hit = await svc.sampling_price_for(s, org, "<=200 t", p1)
        # (2+3) x 60 + 4 x 40 x 1.25 + 100
        assert hit.rate == 300 + 200 + 100
        assert hit.breakdown["missing"] == []
        hit = await svc.sampling_price_for(s, org, "<=200 t", p1, run_hours=5)
        assert hit.rate == 7 * 60 + 200 + 100
        assert (await svc.sampling_price_for(s, org, ">800 t", p1)).rate == 2500


async def test_class_for_tonnage():
    classes = [CostSheetMachineClass(name="<=200 t", tonnage_max=200),
               CostSheetMachineClass(name="200-450 t", tonnage_min=200, tonnage_max=450),
               CostSheetMachineClass(name=">800 t", tonnage_min=800)]
    assert svc.class_for_tonnage(classes, 150) == "<=200 t"
    assert svc.class_for_tonnage(classes, 200) == "<=200 t"
    assert svc.class_for_tonnage(classes, 350) == "200-450 t"
    assert svc.class_for_tonnage(classes, 600) is None
    assert svc.class_for_tonnage(classes, 1000) == ">800 t"


async def test_stale_status_follows_the_review_setting(session_factory, world):
    org = world["org_id"]
    async with session_factory() as s:
        st = await svc.stale_status(s, org)
        assert st["stale"] is True and st["reason"] == "no_published_version"
    await _published(session_factory, org, valid_from=date(2025, 1, 1),
                     published_at=datetime(2025, 1, 1),
                     rates=[dict(department_id=world["tool"], hourly_rate=1)])
    async with session_factory() as s:
        st = await svc.stale_status(s, org, today=date(2025, 12, 31))
        assert st["stale"] is False and st["due_on"] == "2026-01-01"
        assert (await svc.stale_status(s, org, today=date(2026, 1, 1)))["stale"] is True
        await svc.set_setting(s, org, "cost_sheet_review_months", "24")
        await s.commit()
        st = await svc.stale_status(s, org, today=date(2026, 6, 1))
        assert st["stale"] is False and st["review_months"] == 24


async def test_add_months_clamps():
    assert svc.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert svc.add_months(date(2026, 11, 15), 14) == date(2028, 1, 15)


# ---------------------------------------------------------------- API + rights

async def test_read_is_open_write_needs_finance(client, eng_auth, admin_auth, world,
                                                session_factory):
    res = await client.get(API, headers=eng_auth)
    assert res.status_code == 200
    body = res.json()
    assert body["can_edit"] is False and body["versions"] == []
    assert any(d["name"] == "Finance" for d in body["departments"])
    assert (await client.post(f"{API}/drafts", json={}, headers=eng_auth)).status_code == 403

    async with session_factory() as s:
        s.add(UserDepartment(user_id=world["engineer_id"], department_id=world["fin"]))
        await s.commit()
    assert (await client.get(API, headers=eng_auth)).json()["can_edit"] is True
    assert (await client.post(f"{API}/drafts", json={}, headers=eng_auth)).status_code == 201


async def test_admin_acting_as_is_that_department_only(client, admin_auth, world):
    assert (await client.get(API, headers=admin_auth)).json()["can_edit"] is True
    as_tool = {**admin_auth, HEADER: str(world["tool"])}
    assert (await client.get(API, headers=as_tool)).json()["can_edit"] is False
    assert (await client.post(f"{API}/drafts", json={}, headers=as_tool)).status_code == 403
    as_fin = {**admin_auth, HEADER: str(world["fin"])}
    assert (await client.post(f"{API}/drafts", json={}, headers=as_fin)).status_code == 201


async def test_draft_edit_publish_freeze_and_chain(client, admin_auth, world):
    t, p1 = world["tool"], world["p1"]
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    assert d["version"] == 1 and d["status"] == "draft"
    # one draft at a time
    assert (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).status_code == 409
    # an empty version cannot be published
    res = await client.post(f"{API}/versions/{d['id']}/publish",
                            json={"valid_from": "2026-01-01"}, headers=admin_auth)
    assert res.status_code == 422

    res = await client.post(f"{API}/versions/{d['id']}/rates", json={
        "department_id": t, "hourly_rate": 50}, headers=admin_auth)
    assert res.status_code == 201, res.text
    res = await client.post(f"{API}/versions/{d['id']}/rates", json={
        "department_id": t, "position": "Engineer", "plant_id": p1, "hourly_rate": 70,
        "currency": "usd"}, headers=admin_auth)
    rows = res.json()["rates"]
    assert rows[1]["currency"] == "USD"
    # duplicate key
    res = await client.post(f"{API}/versions/{d['id']}/rates", json={
        "department_id": t, "position": "engineer", "plant_id": p1, "hourly_rate": 1},
        headers=admin_auth)
    assert res.status_code == 409
    # negative
    res = await client.patch(f"{API}/versions/{d['id']}/rates/{rows[0]['id']}",
                             json={"hourly_rate": -1}, headers=admin_auth)
    assert res.status_code == 422
    res = await client.patch(f"{API}/versions/{d['id']}/rates/{rows[0]['id']}",
                             json={"hourly_rate": 52.5}, headers=admin_auth)
    assert res.json()["rates"][0]["hourly_rate"] == 52.5
    res = await client.post(f"{API}/versions/{d['id']}/overheads", json={
        "kind": "percent", "value": 10}, headers=admin_auth)
    assert res.json()["rates"][0]["effective_rate"] == 57.75

    res = await client.post(f"{API}/versions/{d['id']}/publish", json={
        "valid_from": "2026-01-01", "note": "Budget 2026"}, headers=admin_auth)
    assert res.status_code == 200
    assert res.json()["status"] == "published" and res.json()["valid_to"] is None
    # frozen
    res = await client.patch(f"{API}/versions/{d['id']}/rates/{rows[0]['id']}",
                             json={"hourly_rate": 1}, headers=admin_auth)
    assert res.status_code == 409
    assert (await client.delete(f"{API}/versions/{d['id']}",
                                headers=admin_auth)).status_code == 409

    # v2 copies v1, must start after it
    d2 = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    assert d2["version"] == 2 and len(d2["rates"]) == 2 and len(d2["overheads"]) == 1
    res = await client.post(f"{API}/versions/{d2['id']}/publish",
                            json={"valid_from": "2026-01-01"}, headers=admin_auth)
    assert res.status_code == 422
    r0 = d2["rates"][0]["id"]
    await client.patch(f"{API}/versions/{d2['id']}/rates/{r0}", json={"hourly_rate": 60},
                       headers=admin_auth)
    await client.delete(f"{API}/versions/{d2['id']}/rates/{d2['rates'][1]['id']}",
                        headers=admin_auth)
    await client.post(f"{API}/versions/{d2['id']}/rates", json={
        "department_id": world["qa"], "hourly_rate": 45}, headers=admin_auth)

    diff = (await client.get(f"{API}/versions/{d2['id']}/diff", headers=admin_auth)).json()
    assert diff["from_version"] == 1 and diff["to_version"] == 2
    assert diff["rates"]["changed"][0]["changes"]["hourly_rate"] == {"old": 52.5, "new": 60}
    assert diff["rates"]["changed"][0]["pct"] == 14.3
    assert len(diff["rates"]["added"]) == 1 and len(diff["rates"]["removed"]) == 1
    assert diff["overheads"] == {"added": [], "removed": [], "changed": []}

    res = await client.post(f"{API}/versions/{d2['id']}/publish",
                            json={"valid_from": "2026-07-01"}, headers=admin_auth)
    assert res.status_code == 200
    ov = (await client.get(API, headers=admin_auth)).json()
    v1 = next(v for v in ov["versions"] if v["version"] == 1)
    assert v1["valid_to"] == "2026-06-30"
    assert ov["draft_version_id"] is None
    lookup = (await client.get(f"{API}/lookup/rate", params={
        "department_id": t, "on_date": "2026-03-01"}, headers=admin_auth)).json()
    assert lookup["rate"] == 57.75 and lookup["version"] == 1


async def test_delete_draft_and_versions_are_org_scoped(client, admin_auth, world,
                                                         session_factory):
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    assert (await client.delete(f"{API}/versions/{d['id']}",
                                headers=admin_auth)).status_code == 204
    from app.models.entities import Organization
    async with session_factory() as s:
        other = Organization(name="Other", code="other", is_active=True)
        s.add(other)
        await s.flush()
        oid = other.id
        await s.commit()
    vid = await _published(session_factory, oid, rates=[
        dict(department_id=world["tool"], hourly_rate=1)])
    assert (await client.get(f"{API}/versions/{vid}", headers=admin_auth)).status_code == 404


async def test_row_validation(client, admin_auth, world):
    d = (await client.post(f"{API}/drafts", json={}, headers=admin_auth)).json()
    base = f"{API}/versions/{d['id']}"
    assert (await client.post(f"{base}/rates", json={"hourly_rate": 5},
                              headers=admin_auth)).status_code == 422
    assert (await client.post(f"{base}/rates", json={"department_id": world["tool"],
                                                     "hourly_rate": 5, "plant_id": 99999},
                              headers=admin_auth)).status_code == 422
    assert (await client.post(f"{base}/sampling", json={"machine_class": "x", "mode": "flat"},
                              headers=admin_auth)).status_code == 422
    assert (await client.post(f"{base}/sampling", json={
        "machine_class": "x", "mode": "components", "labour_hours": 2},
        headers=admin_auth)).status_code == 422
    res = await client.post(f"{base}/machines", json={"machine_class": "<=200 t",
                                                      "hourly_rate": 60}, headers=admin_auth)
    assert res.status_code == 201
    res = await client.post(f"{base}/sampling", json={
        "machine_class": "<=200 t", "mode": "components", "setup_hours": 1,
        "run_hours_default": 1, "handling_cost": 10}, headers=admin_auth)
    assert res.json()["sampling_rates"][0]["computed_price"] == 130


async def test_machine_classes_and_settings(client, admin_auth, eng_auth, world):
    res = await client.post(f"{API}/machine-classes", json={
        "name": "<=200 t", "tonnage_max": 200}, headers=admin_auth)
    assert res.status_code == 201
    cid = res.json()["id"]
    assert (await client.post(f"{API}/machine-classes", json={"name": "<=200 t"},
                              headers=admin_auth)).status_code == 409
    assert (await client.post(f"{API}/machine-classes", json={"name": "x"},
                              headers=eng_auth)).status_code == 403
    await client.patch(f"{API}/machine-classes/{cid}", json={"sort_order": 3},
                       headers=admin_auth)
    assert (await client.get(f"{API}/machine-classes", headers=eng_auth)).json()[0][
        "sort_order"] == 3
    assert (await client.delete(f"{API}/machine-classes/{cid}",
                                headers=admin_auth)).status_code == 204
    assert (await client.get(f"{API}/machine-classes", headers=eng_auth)).json() == []

    assert (await client.get(f"{API}/settings", headers=eng_auth)).json() == {
        "review_months": 12}
    assert (await client.put(f"{API}/settings", json={"review_months": 6},
                             headers=eng_auth)).status_code == 403
    assert (await client.put(f"{API}/settings", json={"review_months": 6},
                             headers=admin_auth)).json() == {"review_months": 6}
    assert (await client.get(API, headers=eng_auth)).json()["stale"]["review_months"] == 6


async def test_export_csv_and_xlsx(client, admin_auth, world, session_factory):
    vid = await _published(session_factory, world["org_id"], rates=[
        dict(department_id=world["tool"], position="Engineer", hourly_rate=70)])
    res = await client.get(f"{API}/versions/{vid}/export", params={"format": "csv"},
                           headers=admin_auth)
    assert res.status_code == 200
    text = res.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Department;Position;Plant")
    assert "Tooling-CS;Engineer;All plants;70.00;70.00;EUR" in text
    res = await client.get(f"{API}/versions/{vid}/export", headers=admin_auth)
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(res.content))
    assert wb.sheetnames == ["Positions", "Machines", "Sampling", "Overheads"]
    assert wb["Positions"]["B4"].value == "Engineer"


async def test_reference_rates_reads_the_current_version(client, eng_auth, world,
                                                         session_factory):
    t, p1, p2 = world["tool"], world["p1"], world["p2"]
    async with session_factory() as s:
        s.add(DepartmentRate(department_id=t, plant_id=p1, hourly_rate=11.0,
                             min_factor=0.6, effective_from=date(2020, 1, 1)))
        await s.commit()
    legacy = (await client.get("/api/v1/changes/reference/rates", headers=eng_auth)).json()
    assert legacy == [{"department_id": t, "plant_id": p1, "hourly_rate": 11.0,
                       "min_factor": 0.6}]
    await _published(session_factory, world["org_id"], valid_from=date(2026, 1, 1), rates=[
        dict(department_id=t, plant_id=p1, hourly_rate=65, min_factor=0.6),
        dict(department_id=t, hourly_rate=50),
        dict(department_id=t, position="Engineer", hourly_rate=99),
    ])
    rows = (await client.get("/api/v1/changes/reference/rates", headers=eng_auth)).json()
    by_plant = {r["plant_id"]: r for r in rows}
    assert by_plant[p1] == {"department_id": t, "plant_id": p1, "hourly_rate": 65.0,
                            "min_factor": 0.6}
    assert by_plant[p2]["hourly_rate"] == 50.0 and by_plant[p2]["min_factor"] == 1.0
    assert len(rows) == 2
