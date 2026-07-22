"""Department merge/retire migration and the can_start_change column."""
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.workflow import (
    Department, UserDepartment, WfTemplate, WfStage, WfStep, WfStepRasic,
)

pytestmark = pytest.mark.asyncio

_MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "032_change_starter_departments.py"


def _load_migration_032():
    """Load the migration module by file path (its filename starts with a
    digit, so a normal import statement can't reach it).

    `backend/` is itself a package named `alembic` (the real migrations
    directory) and it sits on sys.path because tests/ is a package too --
    that shadows the real `alembic` *distribution* the migration needs for
    `from alembic import op`. Purge any already-shadowed `alembic` modules
    and temporarily drop backend/ from sys.path while importing the real
    package, so it lands in sys.modules before we exec the migration file.
    """
    backend_dir = str(_MIG.resolve().parents[2])

    for name in list(sys.modules):
        if name == "alembic" or name.startswith("alembic."):
            mod_file = getattr(sys.modules[name], "__file__", "") or ""
            if mod_file.startswith(backend_dir):
                del sys.modules[name]

    original_path = sys.path[:]
    sys.path[:] = [p for p in sys.path if p not in ("", backend_dir)]
    try:
        import alembic  # noqa: F401
        import alembic.op  # noqa: F401
    finally:
        sys.path[:] = original_path

    spec = importlib.util.spec_from_file_location("migration_032", _MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration_032 = _load_migration_032()


async def _run_migration(db_engine):
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: migration_032._merge_and_retire(sync_conn))


async def _seed_departments(session_factory):
    """Seed the full set of duplicate/target/retire/starter departments used
    by the migration, plus a template/stage/step to hang RASIC rows off of."""
    names = [
        "Tool Engineer", "Tool design", "Manufacturing Engineer", "IE",
        "Developer", "APQP", "Operations Manager",
        "Sales", "Project Manager", "R&D",
    ]
    async with session_factory() as s:
        depts = {}
        for i, name in enumerate(names):
            d = Department(name=name, flow_type="action", is_active=True, sort_order=i)
            s.add(d)
            depts[name] = d
        await s.flush()

        template = WfTemplate(name="ECR", version=1, is_active=True, created_by=1)
        s.add(template)
        await s.flush()
        stage = WfStage(template_id=template.id, stage_order=1, name="Stage 1")
        s.add(stage)
        await s.flush()
        step = WfStep(stage_id=stage.id, step_name="Step 1", position_in_stage=1)
        s.add(step)
        await s.flush()

        ids = {name: d.id for name, d in depts.items()}
        ids["_step_id"] = step.id
        await s.commit()
        return ids


async def test_department_has_can_start_change_defaulting_false(session_factory):
    async with session_factory() as s:
        d = Department(name="Fresh Dept", flow_type="action", is_active=True, sort_order=1)
        s.add(d)
        await s.commit()
        assert d.can_start_change is False


async def test_can_start_change_is_settable(session_factory):
    async with session_factory() as s:
        d = Department(name="Starter Dept", flow_type="action", is_active=True,
                       sort_order=1, can_start_change=True)
        s.add(d)
        await s.commit()
        row = (await s.execute(
            select(Department).where(Department.name == "Starter Dept")
        )).scalar_one()
        assert row.can_start_change is True


async def test_merge_repoints_rasic_to_targets(db_engine, session_factory):
    ids = await _seed_departments(session_factory)

    async with session_factory() as s:
        s.add_all([
            WfStepRasic(step_id=ids["_step_id"], department_id=ids["Tool Engineer"], rasic_letter="R"),
            WfStepRasic(step_id=ids["_step_id"], department_id=ids["Manufacturing Engineer"], rasic_letter="A"),
        ])
        await s.commit()

    await _run_migration(db_engine)

    async with session_factory() as s:
        rows = (await s.execute(select(WfStepRasic))).scalars().all()
        dept_ids = {r.department_id for r in rows}
        assert ids["Tool design"] in dept_ids
        assert ids["IE"] in dept_ids
        assert ids["Tool Engineer"] not in dept_ids
        assert ids["Manufacturing Engineer"] not in dept_ids


async def test_merge_collapses_pk_collision_and_repoints_solo_member(db_engine, session_factory, seed):
    ids = await _seed_departments(session_factory)
    admin_id = seed["admin_id"]
    engineer_id = seed["engineer_id"]

    async with session_factory() as s:
        # admin belongs to BOTH the duplicate and the target -> collision path.
        s.add_all([
            UserDepartment(user_id=admin_id, department_id=ids["Tool Engineer"]),
            UserDepartment(user_id=admin_id, department_id=ids["Tool design"]),
            # engineer belongs ONLY to the duplicate -> must be repointed.
            UserDepartment(user_id=engineer_id, department_id=ids["Tool Engineer"]),
        ])
        await s.commit()

    await _run_migration(db_engine)

    async with session_factory() as s:
        admin_rows = (await s.execute(
            select(UserDepartment).where(UserDepartment.user_id == admin_id)
        )).scalars().all()
        assert len(admin_rows) == 1
        assert admin_rows[0].department_id == ids["Tool design"]

        eng_rows = (await s.execute(
            select(UserDepartment).where(UserDepartment.user_id == engineer_id)
        )).scalars().all()
        assert len(eng_rows) == 1
        assert eng_rows[0].department_id == ids["Tool design"]


async def test_retirement_marks_exactly_the_five_departments_inactive(db_engine, session_factory):
    ids = await _seed_departments(session_factory)

    await _run_migration(db_engine)

    retired = {"Developer", "Tool Engineer", "Manufacturing Engineer", "APQP", "Operations Manager"}
    async with session_factory() as s:
        rows = (await s.execute(select(Department))).scalars().all()
        for row in rows:
            if row.name in retired:
                assert row.is_active is False, row.name
            else:
                assert row.is_active is True, row.name


async def test_starter_seeding_marks_exactly_the_five_can_start_change(db_engine, session_factory):
    ids = await _seed_departments(session_factory)

    await _run_migration(db_engine)

    starters = {"Sales", "Project Manager", "Tool design", "IE", "R&D"}
    async with session_factory() as s:
        rows = (await s.execute(select(Department))).scalars().all()
        for row in rows:
            if row.name in starters:
                assert row.can_start_change is True, row.name
            else:
                assert row.can_start_change is False, row.name


async def test_row_count_conserved_on_wf_step_rasic(db_engine, session_factory):
    ids = await _seed_departments(session_factory)

    async with session_factory() as s:
        s.add_all([
            WfStepRasic(step_id=ids["_step_id"], department_id=ids["Tool Engineer"], rasic_letter="R"),
            WfStepRasic(step_id=ids["_step_id"], department_id=ids["Manufacturing Engineer"], rasic_letter="A"),
            WfStepRasic(step_id=ids["_step_id"], department_id=ids["Tool design"], rasic_letter="S"),
        ])
        await s.commit()

    async with session_factory() as s:
        before = (await s.execute(select(func.count()).select_from(WfStepRasic))).scalar_one()

    await _run_migration(db_engine)

    async with session_factory() as s:
        after = (await s.execute(select(func.count()).select_from(WfStepRasic))).scalar_one()

    assert before == after


async def test_migration_is_noop_when_duplicate_departments_absent(db_engine, session_factory):
    # Only some starter/retire departments exist; the merge duplicates do not.
    async with session_factory() as s:
        d = Department(name="Some Dept", flow_type="action", is_active=True, sort_order=1)
        s.add(d)
        await s.commit()

    # Must not raise.
    await _run_migration(db_engine)

    async with session_factory() as s:
        row = (await s.execute(
            select(Department).where(Department.name == "Some Dept")
        )).scalar_one()
        assert row.is_active is True
        assert row.can_start_change is False
