"""Task 21: plant consolidation self-heal — merges the duplicate "USA" plant
into the canonical "USA Toccoa" plant (repointing every plant_id FK) and
deactivates "Main Factory" test junk. See app.services.plant_repair.
"""
import pytest
from sqlalchemy import select

from app.models.entities import Plant, Project
from app.models.change import ChangeRequest, change_affected_plants
from app.models.change_cost import AssessmentCostLine, DepartmentRate
from app.models.workflow import Department
from app.services.plant_repair import repair_plants


async def _mk_change(session, seed, number):
    chg = ChangeRequest(
        change_number=number, title="x", reason="y", change_type="physical_part",
        project_id=seed["project_id"], raised_by=seed["admin_id"], status="captured",
    )
    session.add(chg)
    await session.flush()
    return chg


@pytest.mark.asyncio
async def test_merges_usa_dup_and_repoints_all_fks(session_factory, seed):
    async with session_factory() as s:
        org_id = seed["org_id"]
        canonical = Plant(organization_id=org_id, name="USA Toccoa", code="usa-toccoa",
                           location="Toccoa, GA, USA", is_active=True)
        dup = Plant(organization_id=org_id, name="USA", code="USA",
                    location="US", is_active=True)
        s.add_all([canonical, dup])
        await s.flush()

        dept = Department(name="R&D", flow_type="action", is_active=True, sort_order=1)
        s.add(dept)
        await s.flush()

        # A cost line on the dup plant.
        chg = await _mk_change(s, seed, "PR-001")
        from app.models.change import ChangeAssessment
        assessment = ChangeAssessment(change_id=chg.id, department_id=dept.id,
                                       stage_order=1, rasic_letter="R", status="pending")
        s.add(assessment)
        await s.flush()
        cost_line = AssessmentCostLine(assessment_id=assessment.id, plant_id=dup.id,
                                        cost_kind="one_time", demand_hours=2.0)
        s.add(cost_line)

        # A DepartmentRate on the dup plant, no clash with canonical.
        rate = DepartmentRate(department_id=dept.id, plant_id=dup.id, hourly_rate=21.5)
        s.add(rate)

        # A project pointing at the dup plant.
        project = Project(plant_id=dup.id, name="Dup Plant Project", code="dpp", status="active")
        s.add(project)

        # An affected-plants row on the dup plant only.
        chg2 = await _mk_change(s, seed, "PR-002")
        s.add(chg2)
        await s.flush()
        await s.execute(change_affected_plants.insert().values(
            change_id=chg2.id, plant_id=dup.id))

        # Another change already associated with BOTH dup and canonical —
        # the merge must not explode on the composite-PK unique constraint.
        chg3 = await _mk_change(s, seed, "PR-003")
        await s.execute(change_affected_plants.insert().values(
            [{"change_id": chg3.id, "plant_id": dup.id},
             {"change_id": chg3.id, "plant_id": canonical.id}]))

        await s.commit()
        ids = {"dup": dup.id, "canonical": canonical.id, "cost_line": cost_line.id,
               "project": project.id, "chg2": chg2.id, "chg3": chg3.id, "dept": dept.id}

    async with session_factory() as s:
        report = await repair_plants(s)
        await s.commit()

    assert report["merged_usa_dup"] is True
    assert report["dup_plant_id"] == ids["dup"]
    assert report["canonical_plant_id"] == ids["canonical"]
    assert report["cost_lines_repointed"] == 1
    assert report["projects_repointed"] == 1
    assert report["department_rates_repointed"] == 1
    assert report["affected_plants_repointed"] == 2  # chg2 + chg3's dup row

    async with session_factory() as s:
        # dup plant row gone
        assert await s.get(Plant, ids["dup"]) is None
        canonical_plant = await s.get(Plant, ids["canonical"])
        assert canonical_plant is not None

        cost_line = await s.get(AssessmentCostLine, ids["cost_line"])
        assert cost_line.plant_id == ids["canonical"]

        project = await s.get(Project, ids["project"])
        assert project.plant_id == ids["canonical"]

        rates = (await s.execute(select(DepartmentRate).where(
            DepartmentRate.department_id == ids["dept"]))).scalars().all()
        assert len(rates) == 1
        assert rates[0].plant_id == ids["canonical"]

        # chg2: now associated with canonical, not dup
        rows2 = (await s.execute(select(change_affected_plants.c.plant_id).where(
            change_affected_plants.c.change_id == ids["chg2"]))).scalars().all()
        assert rows2 == [ids["canonical"]]

        # chg3: had both — de-duped down to just canonical, no unique-constraint blowup
        rows3 = (await s.execute(select(change_affected_plants.c.plant_id).where(
            change_affected_plants.c.change_id == ids["chg3"]))).scalars().all()
        assert rows3 == [ids["canonical"]]


@pytest.mark.asyncio
async def test_deactivates_main_factory_without_deleting(session_factory, seed):
    async with session_factory() as s:
        mf = Plant(organization_id=seed["org_id"], name="Main Factory", code="main-plant",
                    location="Germany", is_active=True)
        s.add(mf)
        await s.flush()
        project = Project(plant_id=mf.id, name="Uses Main Factory", code="umf", status="active")
        s.add(project)
        await s.commit()
        mf_id = mf.id
        project_id = project.id

    async with session_factory() as s:
        report = await repair_plants(s)
        await s.commit()

    assert report["deactivated_main_factory"] is True

    async with session_factory() as s:
        mf = await s.get(Plant, mf_id)
        assert mf is not None  # not deleted — FK safety
        assert mf.is_active is False
        project = await s.get(Project, project_id)
        assert project.plant_id == mf_id  # FK untouched


@pytest.mark.asyncio
async def test_idempotent_second_run_is_noop(session_factory, seed):
    async with session_factory() as s:
        canonical = Plant(organization_id=seed["org_id"], name="USA Toccoa", code="usa-toccoa",
                           is_active=True)
        dup = Plant(organization_id=seed["org_id"], name="USA", code="USA", is_active=True)
        mf = Plant(organization_id=seed["org_id"], name="Main Factory", code="main-plant",
                   is_active=True)
        s.add_all([canonical, dup, mf])
        await s.commit()

    async with session_factory() as s:
        first = await repair_plants(s)
        await s.commit()
    assert first["merged_usa_dup"] is True
    assert first["deactivated_main_factory"] is True

    async with session_factory() as s:
        second = await repair_plants(s)
        await s.commit()

    assert second["merged_usa_dup"] is False
    assert second["deactivated_main_factory"] is False
    assert second["cost_lines_repointed"] == 0
    assert second["projects_repointed"] == 0
    assert second["department_rates_repointed"] == 0
    assert second["affected_plants_repointed"] == 0


@pytest.mark.asyncio
async def test_noop_when_no_dup_exists(session_factory, seed):
    async with session_factory() as s:
        canonical = Plant(organization_id=seed["org_id"], name="USA Toccoa", code="usa-toccoa",
                           is_active=True)
        s.add(canonical)
        await s.commit()

    async with session_factory() as s:
        report = await repair_plants(s)
        await s.commit()

    assert report["merged_usa_dup"] is False
    assert report["dup_plant_id"] is None
    assert report["deactivated_main_factory"] is False

    async with session_factory() as s:
        plants = (await s.execute(select(Plant))).scalars().all()
        # seed's own "Plant" + canonical only
        names = {p.name for p in plants}
        assert "USA Toccoa" in names
        assert "USA" not in names
