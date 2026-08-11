"""Migration 043: the department roster becomes the ECR nine + Quality.

Runs the migration against a seeded roster the way test_change_starter_departments
does — by loading the migration module and calling upgrade() on a live bind.
"""
import pytest
from sqlalchemy import select

from app.models.workflow import Department
from tests.test_change_starter_departments import _load_migration_032  # noqa: F401

pytestmark = pytest.mark.asyncio

BEFORE = [
    "Developer", "APQP", "Sales", "Project Manager", "Planner/Scheduler",
    "Operations Manager", "R&D", "Tooling Engineer", "Manufacturing Engineer",
    "Quality", "Logistics", "Production", "Purchasing", "Production control",
    "Process Engineer",
]
ECR_NINE = ["Sales", "Project Manager", "APQP", "Tool Engineer",
            "Manufacturing Engineer", "Process Engineer", "Development",
            "Scheduling", "Packaging Engineer"]


def _load_migration_043():
    import importlib.util
    from pathlib import Path
    path = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
            / "043_ecr_role_cleanup.py")
    spec = importlib.util.spec_from_file_location("mig_043", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _run(db_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    mod = _load_migration_043()
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: _apply(sync_conn, mod))


def _apply(sync_conn, mod):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        mod.upgrade()


async def _seed(session_factory, names=None):
    async with session_factory() as s:
        for i, name in enumerate(names or BEFORE, start=1):
            s.add(Department(name=name, flow_type="action", is_active=True,
                             sort_order=i))
        await s.commit()


async def test_renames_create_and_deactivate(db_engine, session_factory, seed):
    await _seed(session_factory)
    await _run(db_engine)
    async with session_factory() as s:
        rows = {d.name: d for d in
                (await s.execute(select(Department))).scalars().all()}
    # renamed
    for old in ("R&D", "Tooling Engineer", "Planner/Scheduler"):
        assert old not in rows
    for new in ("Development", "Tool Engineer", "Scheduling"):
        assert new in rows and rows[new].is_active is True
    # created
    assert "Packaging Engineer" in rows
    assert rows["Packaging Engineer"].is_active is True
    # Quality stays active — it co-signs approvals
    assert rows["Quality"].is_active is True
    # non-ECR roles step out
    for name in ("Logistics", "Production", "Purchasing", "Production control",
                 "Operations Manager", "Developer"):
        assert rows[name].is_active is False, name
    # ECR order
    assert [rows[n].sort_order for n in ECR_NINE] == list(range(1, 10))
    assert rows["Quality"].sort_order == 10
    assert all(rows[n].sort_order > 10 for n in ("Logistics", "Developer"))


async def test_rename_target_already_present_retires_the_source(
        db_engine, session_factory, seed):
    """A partial history where both names exist: the stale source is retired
    rather than colliding on the unique name."""
    await _seed(session_factory, names=["R&D", "Development", "Quality"])
    await _run(db_engine)
    async with session_factory() as s:
        rows = {d.name: d for d in
                (await s.execute(select(Department))).scalars().all()}
    assert rows["R&D"].is_active is False
    assert rows["Development"].is_active is True


async def test_missing_departments_are_skipped(db_engine, session_factory, seed):
    """An install that never had these rows still upgrades cleanly."""
    await _seed(session_factory, names=["Quality"])
    await _run(db_engine)
    async with session_factory() as s:
        rows = {d.name: d for d in
                (await s.execute(select(Department))).scalars().all()}
    assert rows["Quality"].is_active is True
    assert "Packaging Engineer" in rows
