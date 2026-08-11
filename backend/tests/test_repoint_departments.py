"""Migration 045: references move off the legacy department rows, which stay
behind as tombstones with nothing pointing at them."""
import pytest
from sqlalchemy import select

from app.models.workflow import Department, UserDepartment
from app.models.change import ChangeConcern, ChangeAssessment

pytestmark = pytest.mark.asyncio


def _load():
    # backend/alembic/ shadows the real alembic distribution; this helper
    # purges it and imports the real package first (see its docstring).
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()
    import importlib.util
    from pathlib import Path
    path = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
            / "045_repoint_legacy_department_refs.py")
    spec = importlib.util.spec_from_file_location("mig_045", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _apply(sync_conn, mod):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        mod.upgrade()


async def _run(db_engine):
    mod = _load()
    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: _apply(c, mod))


@pytest.fixture
async def legacy(session_factory, seed):
    """Both names present, references parked on the legacy row."""
    async with session_factory() as s:
        old = Department(name="R&D", flow_type="action", is_active=False)
        new = Department(name="Development", flow_type="action", is_active=True)
        s.add_all([old, new])
        await s.flush()
        # engineer sits only on the legacy row; admin sits on BOTH (dedupe path)
        s.add_all([
            UserDepartment(user_id=seed["engineer_id"], department_id=old.id),
            UserDepartment(user_id=seed["admin_id"], department_id=old.id),
            UserDepartment(user_id=seed["admin_id"], department_id=new.id),
        ])
        await s.commit()
        return {"old": old.id, "new": new.id}


async def test_memberships_move_and_duplicates_collapse(
        db_engine, session_factory, seed, legacy):
    await _run(db_engine)
    async with session_factory() as s:
        rows = (await s.execute(select(UserDepartment))).scalars().all()
    assert all(r.department_id == legacy["new"] for r in rows)
    # the engineer moved, the admin's rows collapsed into one
    assert sorted(r.user_id for r in rows) == sorted(
        [seed["engineer_id"], seed["admin_id"]])


async def test_change_references_move(db_engine, session_factory, seed, legacy):
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-RP-1", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], status="in_assessment")
        s.add(c)
        await s.flush()
        s.add_all([
            ChangeAssessment(change_id=c.id, department_id=legacy["old"]),
            ChangeConcern(change_id=c.id, kind="needs_info", note="n",
                          raised_by=seed["admin_id"], department_id=legacy["old"]),
        ])
        await s.commit()

    await _run(db_engine)

    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment))).scalars().all()
        k = (await s.execute(select(ChangeConcern))).scalars().all()
    assert [x.department_id for x in a] == [legacy["new"]]
    assert [x.department_id for x in k] == [legacy["new"]]


async def test_tombstone_survives_with_no_references(
        db_engine, session_factory, legacy):
    await _run(db_engine)
    async with session_factory() as s:
        old = await s.get(Department, legacy["old"])
        left = (await s.execute(select(UserDepartment).where(
            UserDepartment.department_id == legacy["old"]))).scalars().all()
    assert old is not None and old.is_active is False
    assert left == []


async def test_missing_pair_is_skipped(db_engine, session_factory, seed):
    """Only the new name present — nothing to move, no error."""
    async with session_factory() as s:
        s.add(Department(name="Development", flow_type="action", is_active=True))
        await s.commit()
    await _run(db_engine)   # must not raise
