"""Migration 048: Project Manager joins Sales as a department that may raise
change requests."""
import pytest
from sqlalchemy import select

from app.models.workflow import Department

pytestmark = pytest.mark.asyncio


def _load():
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()      # purges the shadowed alembic package first
    import importlib.util
    from pathlib import Path
    path = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
            / "048_pm_may_start_changes.py")
    spec = importlib.util.spec_from_file_location("mig_048", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _apply(sync_conn, mod):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        mod.upgrade()


async def test_pm_gains_the_flag_and_sales_keeps_it(db_engine, session_factory, seed):
    async with session_factory() as s:
        s.add_all([
            Department(name="Sales", flow_type="action", is_active=True,
                       can_start_change=True),
            Department(name="Project Manager", flow_type="action", is_active=True,
                       can_start_change=False),
            Department(name="Quality", flow_type="action", is_active=True,
                       can_start_change=False),
        ])
        await s.commit()

    mod = _load()
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: _apply(c, mod))

    async with session_factory() as s:
        rows = {d.name: d.can_start_change for d in
                (await s.execute(select(Department))).scalars().all()}
    assert rows["Project Manager"] is True
    assert rows["Sales"] is True
    assert rows["Quality"] is False
