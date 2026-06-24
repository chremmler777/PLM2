import pytest
pytestmark = pytest.mark.asyncio


async def test_reference_models_persist(session_factory):
    from app.models.change_cost import DepartmentRate, AssessmentActivity, COST_KINDS
    from app.models.workflow import Department
    from app.models.entities import Organization, Plant
    from datetime import date
    async with session_factory() as s:
        org = Organization(name="O", code="o"); s.add(org); await s.flush()
        plant = Plant(organization_id=org.id, name="Weissenburg", code="WUG"); s.add(plant)
        dep = Department(name="Sales", flow_type="action"); s.add(dep)
        await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id,
                             hourly_rate=50.0, min_factor=0.6, effective_from=date(2026, 1, 1)))
        s.add(AssessmentActivity(department_id=dep.id, label="Angebotserstellung",
                                 sort_order=1, is_active=True))
        await s.commit()
        rate = (await s.execute(__import__("sqlalchemy").select(DepartmentRate))).scalar_one()
        assert rate.hourly_rate == 50.0 and rate.min_factor == 0.6
        assert COST_KINDS == ("one_time", "lifecycle")


async def test_replace_cost_lines_computes_internal_cost(session_factory, seed):
    from sqlalchemy import select
    from datetime import date
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.change_cost import DepartmentRate, AssessmentCostLine
    from app.models.workflow import Department
    from app.models.entities import Plant
    from app.services.cost_service import CostService
    async with session_factory() as s:
        plant = (await s.execute(select(Plant))).scalars().first()
        dep = Department(name="R&D", flow_type="action"); s.add(dep); await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id,
                             hourly_rate=65.0, min_factor=0.6, effective_from=date(2026, 1, 1)))
        change = ChangeRequest(change_number="CR-T-2", project_id=seed["project_id"],
                               title="t", change_type="physical_part", status="in_assessment",
                               raised_by=seed["engineer_id"], lead_id=seed["engineer_id"])
        s.add(change); await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=dep.id, verdict="pending")
        s.add(a); await s.flush()
        await CostService.replace_cost_lines(s, change, a, [
            {"plant_id": plant.id, "cost_kind": "one_time", "demand_hours": 5.0,
             "external_cost": 100.0, "activity_label": "3D-Konstruktion"},
        ], seed["engineer_id"])
        await s.commit()
        line = (await s.execute(select(AssessmentCostLine))).scalar_one()
        assert line.rate_snapshot == 65.0
        assert line.internal_cost == 325.0          # 5h × 65
        assert a.cost_impact == 425.0               # 325 internal + 100 external (one_time)


async def test_summation_rolls_up_by_plant_and_department(session_factory, seed):
    from sqlalchemy import select
    from datetime import date
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.change_cost import DepartmentRate
    from app.models.workflow import Department
    from app.models.entities import Plant
    from app.services.cost_service import CostService
    async with session_factory() as s:
        plant = (await s.execute(select(Plant))).scalars().first()
        dep = Department(name="Sales", flow_type="action"); s.add(dep); await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id,
                             hourly_rate=50.0, min_factor=0.6, effective_from=date(2026, 1, 1)))
        change = ChangeRequest(change_number="CR-T-3", project_id=seed["project_id"],
                               title="t", change_type="physical_part", status="in_assessment",
                               raised_by=seed["engineer_id"], lead_id=seed["engineer_id"])
        s.add(change); await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=dep.id, verdict="pending")
        s.add(a); await s.flush()
        await CostService.replace_cost_lines(s, change, a, [
            {"plant_id": plant.id, "cost_kind": "one_time", "demand_hours": 2.0,
             "external_cost": 50.0, "activity_label": "Angebotserstellung"},
            {"plant_id": plant.id, "cost_kind": "lifecycle", "demand_hours": 1.0,
             "external_cost": 0.0, "activity_label": "Betreuung"},
        ], seed["engineer_id"])
        await s.commit()
        summ = await CostService.summation(s, change)
        assert summ["totals"]["one_time_internal"] == 100.0   # 2h × 50
        assert summ["totals"]["one_time_external"] == 50.0
        assert summ["totals"]["lifecycle_internal"] == 50.0   # 1h × 50
        assert summ["totals"]["grand_total"] == 200.0
        assert summ["by_plant"][0]["plant_id"] == plant.id
        assert summ["by_department"][0]["department_id"] == dep.id


async def test_summation_multi_plant_and_multi_department(session_factory, seed):
    """
    Two plants × two departments → by_plant and by_department each have 2 entries
    with independently verifiable numeric sub-totals.

    Setup
    -----
    Plant A  (from seed)    rate 100 $/h  for dep_x
    Plant B  (new)          rate 200 $/h  for dep_y

    Cost lines (all on the SAME change, different assessments):
      assessment_x (dep_x):
        - plant_A, one_time,   2h internal + 10 external  → internal=200, external=10
        - plant_A, lifecycle,  3h internal + 20 external  → internal=300, external=20
      assessment_y (dep_y):
        - plant_B, one_time,   1h internal + 5 external   → internal=200, external=5
        - plant_B, lifecycle,  4h internal + 15 external  → internal=800, external=15

    Expected by_plant:
      plant_A: one_time_internal=200, one_time_external=10,
               lifecycle_internal=300, lifecycle_external=20
      plant_B: one_time_internal=200, one_time_external=5,
               lifecycle_internal=800, lifecycle_external=15

    Expected by_department:
      dep_x: one_time_internal=200, one_time_external=10,
             lifecycle_internal=300, lifecycle_external=20
      dep_y: one_time_internal=200, one_time_external=5,
             lifecycle_internal=800, lifecycle_external=15

    Grand total = (200+10+300+20) + (200+5+800+15) = 530 + 1020 = 1550
    """
    from sqlalchemy import select
    from datetime import date
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.change_cost import DepartmentRate
    from app.models.workflow import Department
    from app.models.entities import Organization, Plant
    from app.services.cost_service import CostService

    async with session_factory() as s:
        # Plant A comes from seed fixture (already exists)
        plant_a = (await s.execute(select(Plant))).scalars().first()

        # Plant B — new plant
        org_id = (await s.execute(select(Plant))).scalars().first().organization_id
        plant_b = Plant(organization_id=org_id, name="Plant B", code="PLB", is_active=True)
        s.add(plant_b)
        await s.flush()

        # Two departments
        dep_x = Department(name="DepX", flow_type="action")
        dep_y = Department(name="DepY", flow_type="action")
        s.add_all([dep_x, dep_y])
        await s.flush()

        # Rates: dep_x@plant_a=100, dep_y@plant_b=200
        s.add(DepartmentRate(department_id=dep_x.id, plant_id=plant_a.id,
                             hourly_rate=100.0, min_factor=0.6, effective_from=date(2026, 1, 1)))
        s.add(DepartmentRate(department_id=dep_y.id, plant_id=plant_b.id,
                             hourly_rate=200.0, min_factor=0.6, effective_from=date(2026, 1, 1)))
        await s.flush()

        # One change
        change = ChangeRequest(change_number="CR-T-4", project_id=seed["project_id"],
                               title="multi-dim test", change_type="physical_part",
                               status="in_assessment",
                               raised_by=seed["engineer_id"], lead_id=seed["engineer_id"])
        s.add(change)
        await s.flush()

        # Assessment X (dep_x) → cost lines on plant_a
        ax = ChangeAssessment(change_id=change.id, department_id=dep_x.id, verdict="pending")
        s.add(ax)
        await s.flush()
        await CostService.replace_cost_lines(s, change, ax, [
            {"plant_id": plant_a.id, "cost_kind": "one_time",  "demand_hours": 2.0,
             "external_cost": 10.0, "activity_label": "Design"},
            {"plant_id": plant_a.id, "cost_kind": "lifecycle", "demand_hours": 3.0,
             "external_cost": 20.0, "activity_label": "Support"},
        ], seed["engineer_id"])

        # Assessment Y (dep_y) → cost lines on plant_b
        ay = ChangeAssessment(change_id=change.id, department_id=dep_y.id, verdict="pending")
        s.add(ay)
        await s.flush()
        await CostService.replace_cost_lines(s, change, ay, [
            {"plant_id": plant_b.id, "cost_kind": "one_time",  "demand_hours": 1.0,
             "external_cost": 5.0,  "activity_label": "Tooling"},
            {"plant_id": plant_b.id, "cost_kind": "lifecycle", "demand_hours": 4.0,
             "external_cost": 15.0, "activity_label": "Maintenance"},
        ], seed["engineer_id"])

        await s.commit()

        summ = await CostService.summation(s, change)

    # ---- structural checks ----
    assert len(summ["by_plant"]) == 2
    assert len(summ["by_department"]) == 2

    # ---- by_plant numeric sub-totals ----
    pa_entry = next(e for e in summ["by_plant"] if e["plant_id"] == plant_a.id)
    pb_entry = next(e for e in summ["by_plant"] if e["plant_id"] == plant_b.id)

    assert pa_entry["one_time_internal"]  == 200.0   # 2h × 100
    assert pa_entry["one_time_external"]  == 10.0
    assert pa_entry["lifecycle_internal"] == 300.0   # 3h × 100
    assert pa_entry["lifecycle_external"] == 20.0

    assert pb_entry["one_time_internal"]  == 200.0   # 1h × 200
    assert pb_entry["one_time_external"]  == 5.0
    assert pb_entry["lifecycle_internal"] == 800.0   # 4h × 200
    assert pb_entry["lifecycle_external"] == 15.0

    # ---- by_department numeric sub-totals ----
    dx_entry = next(e for e in summ["by_department"] if e["department_id"] == dep_x.id)
    dy_entry = next(e for e in summ["by_department"] if e["department_id"] == dep_y.id)

    assert dx_entry["one_time_internal"]  == 200.0
    assert dx_entry["one_time_external"]  == 10.0
    assert dx_entry["lifecycle_internal"] == 300.0
    assert dx_entry["lifecycle_external"] == 20.0

    assert dy_entry["one_time_internal"]  == 200.0
    assert dy_entry["one_time_external"]  == 5.0
    assert dy_entry["lifecycle_internal"] == 800.0
    assert dy_entry["lifecycle_external"] == 15.0

    # ---- grand total ----
    # plant_a: 200+10+300+20=530  plant_b: 200+5+800+15=1020  total=1550
    assert summ["totals"]["one_time_internal"]  == 400.0   # 200+200
    assert summ["totals"]["one_time_external"]  == 15.0    # 10+5
    assert summ["totals"]["lifecycle_internal"] == 1100.0  # 300+800
    assert summ["totals"]["lifecycle_external"] == 35.0    # 20+15
    assert summ["totals"]["grand_total"]        == 1550.0


async def _captured_change_with_assessment(client, eng_auth, seed, session_factory):
    from datetime import date
    from sqlalchemy import select
    from app.models.workflow import Department
    from app.models.change_cost import DepartmentRate
    from app.models.entities import Plant
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "c", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    async with session_factory() as s:
        plant = (await s.execute(select(Plant))).scalars().first()
        dep = Department(name="Sales", flow_type="action"); s.add(dep); await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id, hourly_rate=50.0,
                             min_factor=0.6, effective_from=date(2026, 1, 1)))
        from app.models.change import ChangeAssessment
        a = ChangeAssessment(change_id=cid, department_id=dep.id, verdict="pending")
        s.add(a); await s.commit()
        return cid, a.id, dep.id, plant.id


async def test_put_and_get_cost_lines_and_summation(client, eng_auth, seed, session_factory):
    cid, aid, dep_id, plant_id = await _captured_change_with_assessment(
        client, eng_auth, seed, session_factory)
    put = await client.put(
        f"/api/v1/changes/{cid}/assessments/{aid}/cost-lines",
        json={"lines": [{"plant_id": plant_id, "cost_kind": "one_time",
                         "demand_hours": 3.0, "external_cost": 10.0,
                         "activity_label": "Angebot"}]},
        headers=eng_auth)
    assert put.status_code == 200, put.text
    assert put.json()[0]["internal_cost"] == 150.0
    got = await client.get(f"/api/v1/changes/{cid}/assessments/{aid}/cost-lines", headers=eng_auth)
    assert len(got.json()) == 1
    summ = await client.get(f"/api/v1/changes/{cid}/summation", headers=eng_auth)
    assert summ.json()["totals"]["grand_total"] == 160.0


@pytest.mark.asyncio
async def test_d1_master_fields_patch(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "d1", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    patch = await client.patch(f"/api/v1/changes/{cid}", json={
        "issuer": "Customer X", "is_series": True, "cm_external": True,
        "implementation_mode": "integrated", "customer_relevant": True,
        "car_line": "VW426"}, headers=eng_auth)
    assert patch.status_code == 200, patch.text
    got = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    body = got.json()
    assert body["issuer"] == "Customer X"
    assert body["is_series"] is True
    assert body["car_line"] == "VW426"


@pytest.mark.asyncio
async def test_reference_endpoints(client, eng_auth, seed, session_factory):
    from datetime import date
    from sqlalchemy import select
    from app.models.workflow import Department
    from app.models.change_cost import DepartmentRate, AssessmentActivity
    from app.models.entities import Plant
    async with session_factory() as s:
        plant = (await s.execute(select(Plant))).scalars().first()
        dep = Department(name="Sales", flow_type="action"); s.add(dep); await s.flush()
        s.add(DepartmentRate(department_id=dep.id, plant_id=plant.id, hourly_rate=50.0,
                             min_factor=0.6, effective_from=date(2026, 1, 1)))
        s.add(AssessmentActivity(department_id=dep.id, label="Angebot", sort_order=1, is_active=True))
        await s.commit()
        dep_id = dep.id
    rates = await client.get("/api/v1/changes/reference/rates", headers=eng_auth)
    assert any(r["hourly_rate"] == 50.0 for r in rates.json())
    acts = await client.get(f"/api/v1/changes/reference/activities?department_id={dep_id}",
                            headers=eng_auth)
    assert acts.json()[0]["label"] == "Angebot"
