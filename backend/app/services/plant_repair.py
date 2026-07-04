"""Plant consolidation self-heal (spec: Phase E Task 21).

Two dev-data problems accumulated in the plants table:
  - A duplicate USA plant: seed_test_data (app.main) creates a plant named
    "USA" as part of the cost-rate reference data, while import_atlas.py
    separately creates the canonical "USA Toccoa" plant. Both exist side by
    side in older DBs, each with its own FK graph (DepartmentRate rows, cost
    lines, projects, affected-plant links).
  - "Main Factory" is Phase-1 smoke-test junk that should no longer be
    selectable, but cannot be deleted outright — projects still point at it.

`repair_plants` merges the USA duplicate into "USA Toccoa" (repointing every
plant_id FK we have — see the grep-derived list below — before deleting the
now-orphaned dup row) and deactivates "Main Factory". Idempotent: a second
run finds no dup and an already-inactive Main Factory, so it no-ops.

Note on Weissenburg/WUG: grepping the codebase found no code that hardcodes
Weissenburg as a *default* plant. What actually happens is a frontend bug —
CostLineGrid.addRow() picked `ratedPlants[0]`, and because Weissenburg's rate
rows were seeded before USA's, Weissenburg often sorted first, so new cost
rows silently defaulted to the German plant. That is fixed on the frontend
via the new `defaultPlantId()` helper, not here — this repair only touches
real plant-row/data problems (the USA dup and Main Factory).
"""
from sqlalchemy import select, delete, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Plant, Project
from app.models.change import change_affected_plants
from app.models.change_cost import AssessmentCostLine, DepartmentRate

CANONICAL_USA_NAME = "USA Toccoa"
DUP_USA_NAME = "USA"
MAIN_FACTORY_NAME = "Main Factory"


async def _repoint_change_affected_plants(session: AsyncSession, dup_id: int, target_id: int) -> int:
    """Repoint change_affected_plants rows from dup_id to target_id, deduping
    against rows that already exist for the target (composite PK on
    (change_id, plant_id) — inserting a row that already exists would
    violate it)."""
    dup_change_ids = (await session.execute(
        select(change_affected_plants.c.change_id)
        .where(change_affected_plants.c.plant_id == dup_id)
    )).scalars().all()
    if not dup_change_ids:
        return 0
    existing_target_change_ids = set((await session.execute(
        select(change_affected_plants.c.change_id)
        .where(change_affected_plants.c.plant_id == target_id)
    )).scalars().all())
    to_insert = [cid for cid in dup_change_ids if cid not in existing_target_change_ids]
    if to_insert:
        await session.execute(insert(change_affected_plants).values(
            [{"change_id": cid, "plant_id": target_id} for cid in to_insert]
        ))
    await session.execute(
        delete(change_affected_plants).where(change_affected_plants.c.plant_id == dup_id)
    )
    return len(dup_change_ids)


async def _repoint_department_rate(session: AsyncSession, dup_id: int, target_id: int) -> int:
    """Repoint department_rate rows, deduping on department_id (no DB unique
    constraint exists, but two rates for the same department at the merged
    plant would be a silent data bug, so keep the target's rate and drop the
    dup's when both exist)."""
    dup_rates = (await session.execute(
        select(DepartmentRate).where(DepartmentRate.plant_id == dup_id)
    )).scalars().all()
    if not dup_rates:
        return 0
    target_dept_ids = set((await session.execute(
        select(DepartmentRate.department_id).where(DepartmentRate.plant_id == target_id)
    )).scalars().all())
    moved = 0
    for dr in dup_rates:
        if dr.department_id in target_dept_ids:
            await session.delete(dr)
        else:
            dr.plant_id = target_id
            target_dept_ids.add(dr.department_id)
            moved += 1
    return moved


async def repair_plants(session: AsyncSession) -> dict:
    """Idempotent plant self-heal. Returns a dict of counters describing what
    was changed (all zero/False on a no-op run)."""
    report = {
        "merged_usa_dup": False,
        "dup_plant_id": None,
        "canonical_plant_id": None,
        "affected_plants_repointed": 0,
        "cost_lines_repointed": 0,
        "projects_repointed": 0,
        "department_rates_repointed": 0,
        "deactivated_main_factory": False,
    }

    dup = (await session.execute(
        select(Plant).where(Plant.name == DUP_USA_NAME))).scalar_one_or_none()
    canonical = (await session.execute(
        select(Plant).where(Plant.name == CANONICAL_USA_NAME))).scalar_one_or_none()

    if dup is not None and canonical is not None and dup.id != canonical.id:
        dup_id, target_id = dup.id, canonical.id

        report["affected_plants_repointed"] = await _repoint_change_affected_plants(
            session, dup_id, target_id)

        cost_result = await session.execute(
            update(AssessmentCostLine)
            .where(AssessmentCostLine.plant_id == dup_id)
            .values(plant_id=target_id)
        )
        report["cost_lines_repointed"] = cost_result.rowcount or 0

        project_result = await session.execute(
            update(Project)
            .where(Project.plant_id == dup_id)
            .values(plant_id=target_id)
        )
        report["projects_repointed"] = project_result.rowcount or 0

        report["department_rates_repointed"] = await _repoint_department_rate(
            session, dup_id, target_id)

        await session.flush()
        await session.delete(dup)
        await session.flush()

        report["merged_usa_dup"] = True
        report["dup_plant_id"] = dup_id
        report["canonical_plant_id"] = target_id

    main_factory = (await session.execute(
        select(Plant).where(Plant.name == MAIN_FACTORY_NAME))).scalar_one_or_none()
    if main_factory is not None and main_factory.is_active:
        main_factory.is_active = False
        report["deactivated_main_factory"] = True

    await session.flush()
    return report
