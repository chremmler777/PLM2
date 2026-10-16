"""ECR-solid close-out area 6 (tasks, notifications, next-action panels).

- A6-01: the task clock's go-live is stamped (migration 143), so a change in
  flight at go-live is not Late without CM_TASK_CLOCK_FROM, and the overdue
  digest's Sales rows count from the same floor as My Tasks."""
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from app.core.config import get_settings
from app.models.change import ChangeChangelog, ChangeRequest
from app.models.cost_sheet import OrgSetting
from tests.test_ecr_solid_l3_review2 import _owing_costing
from tests.test_ecr_solid_tasks import _as, _create, _set, _tasks, team  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _stamp_go_live(session_factory, seed, when: datetime):
    async with session_factory() as s:
        s.add(OrgSetting(organization_id=seed["org_id"], key="cm_task_clock_from",
                         value=when.replace(microsecond=0).isoformat()))
        await s.commit()


# ---------------------------------------------------------------------------
# A6-01 a safe default for the task clock
# ---------------------------------------------------------------------------
async def test_stamped_go_live_keeps_in_flight_row_from_late_without_env(
        client, seed, team, session_factory, monkeypatch):
    monkeypatch.setattr(get_settings(), "cm_task_clock_from", "")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "in flight")
    await _set(session_factory, cid, status="in_assessment")
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=30))
    tool = await _as(client, "Tool Engineer")
    # no stamp: the row counts from its start (negative case)
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["late"] is True
    await _stamp_go_live(session_factory, seed, datetime.utcnow() - timedelta(hours=1))
    row = (await _tasks(client, tool, cid, "costing_input"))[0]
    assert row["late"] is False and row["overdue"] is False


async def test_env_clock_wins_over_the_stamp(client, seed, team, session_factory,
                                             monkeypatch):
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "env wins")
    await _set(session_factory, cid, status="in_assessment")
    await _owing_costing(session_factory, team, cid, datetime.utcnow() - timedelta(days=30))
    await _stamp_go_live(session_factory, seed, datetime.utcnow())
    monkeypatch.setattr(get_settings(), "cm_task_clock_from",
                        (datetime.utcnow() - timedelta(days=60)).date().isoformat())
    tool = await _as(client, "Tool Engineer")
    assert (await _tasks(client, tool, cid, "costing_input"))[0]["late"] is True


async def test_digest_sales_row_counts_from_the_go_live(
        client, seed, team, session_factory, monkeypatch):
    from app.services.overdue_digest import late_by_change
    monkeypatch.setattr(get_settings(), "cm_task_clock_from", "")
    sales = await _as(client, "Sales")
    cid = await _create(client, sales, seed, "old quote")
    old = datetime.utcnow() - timedelta(days=30)
    await _set(session_factory, cid, status="quoting", created_at=old)
    async with session_factory() as s:
        s.add(ChangeChangelog(change_id=cid, action="status_change", action_description="s", performed_by=team["user"]["Sales"], field_name="status", old_value="approved",
                              new_value="quoting", performed_at=old))
        await s.commit()

    async def sales_lines():
        async with session_factory() as s:
            c = await s.get(ChangeRequest, cid)
            got = await late_by_change(s, {cid: c}, datetime.utcnow(), deadlines=False)
        return [t for t in got.get(cid, []) if t.startswith("Sales")]

    assert await sales_lines()                           # late without a floor
    await _stamp_go_live(session_factory, seed, datetime.utcnow() - timedelta(hours=1))
    assert await sales_lines() == []


@pytest.mark.filterwarnings("ignore")
def test_migration_143_stamps_once_and_downgrades(tmp_path):
    from tests.test_change_starter_departments import _load_migration_032
    from tests.test_migration_118_sqlite import _load, _run
    _load_migration_032()
    m = _load("143_task_clock_go_live.py")
    assert (m.revision, m.down_revision) == ("143", "142")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm143.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE organizations (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql(
            "CREATE TABLE org_settings (id INTEGER PRIMARY KEY, organization_id INTEGER, "
            "key VARCHAR(80), value VARCHAR(255), updated_by INTEGER, updated_at DATETIME)")
        conn.exec_driver_sql("INSERT INTO organizations VALUES (1), (2)")
        conn.exec_driver_sql("INSERT INTO org_settings (organization_id, key, value) "
                             "VALUES (2, 'cm_task_clock_from', '2026-11-02')")
    with engine.begin() as conn:
        _run(conn, m.upgrade)
        _run(conn, m.upgrade)                 # repeatable
        rows = dict(conn.execute(sa.text(
            "SELECT organization_id, value FROM org_settings "
            "WHERE key = 'cm_task_clock_from'")).all())
        assert rows[2] == "2026-11-02"        # an admin's value is kept
        assert datetime.fromisoformat(rows[1]) <= datetime.utcnow()
    with engine.begin() as conn:
        _run(conn, m.downgrade)
        assert conn.execute(sa.text("SELECT count(*) FROM org_settings")).scalar() == 0
