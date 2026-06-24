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
