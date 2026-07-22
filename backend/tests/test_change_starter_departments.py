"""Department merge/retire migration and the can_start_change column."""
import pytest
from sqlalchemy import select

from app.models.workflow import Department, UserDepartment

pytestmark = pytest.mark.asyncio


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
