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
