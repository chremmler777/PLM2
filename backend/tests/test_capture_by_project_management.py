"""Migration 152 (Christoph 2026-10-26): capturing a change is Project
Management's job. Sales loses can_start_change, Project Manager keeps it;
downgrade gives it back."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.workflow import Department

pytestmark = pytest.mark.asyncio


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()      # purges the shadowed alembic package first
    path = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
            / "152_capture_by_project_management.py")
    spec = importlib.util.spec_from_file_location("mig_152", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(sync_conn, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        fn()


async def _flags(session_factory) -> dict:
    async with session_factory() as s:
        return {d.name: d.can_start_change for d in
                (await s.execute(select(Department))).scalars().all()}


async def test_sales_loses_the_flag_pm_keeps_it_and_downgrade_restores(
        db_engine, session_factory, seed):
    async with session_factory() as s:
        s.add_all([
            Department(name="Sales", flow_type="action", is_active=True,
                       can_start_change=True),
            Department(name="Project Manager", flow_type="action", is_active=True,
                       can_start_change=True),
            Department(name="Development", flow_type="action", is_active=True,
                       can_start_change=False, can_start_internal_change=True),
        ])
        await s.commit()
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("152", "151")

    for _ in range(2):          # repeatable
        async with db_engine.begin() as conn:
            await conn.run_sync(lambda c: _run(c, mod.upgrade))
        rows = await _flags(session_factory)
        assert rows == {"Sales": False, "Project Manager": True, "Development": False}

    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: _run(c, mod.downgrade))
    rows = await _flags(session_factory)
    assert rows["Sales"] is True and rows["Project Manager"] is True
