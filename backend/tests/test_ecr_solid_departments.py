"""ECR-solid P7/P4: Toolshop is its own department (no price view, no
Tool Engineer rights); Management sees prices (it gives the OK on price
drops and Absorb)."""
import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from app.services.price_redaction import PriceViewer
from app.services.tool_rights import can_edit_tools

pytestmark = pytest.mark.asyncio


async def _member_of(session_factory, seed, name):
    async with session_factory() as s:
        d = Department(name=name, flow_type="action", is_active=True)
        s.add(d); await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=d.id))
        c = ChangeRequest(change_number=f"CR-{name}", project_id=seed["project_id"],
                          title="t", raised_by=seed["admin_id"], status="costing")
        s.add(c); await s.commit()
        return c.id


async def test_management_sees_prices(session_factory, seed):
    cid = await _member_of(session_factory, seed, "Management")
    async with session_factory() as s:
        eng = await s.get(User, seed["engineer_id"])
        assert await PriceViewer(s, eng).may_read(await s.get(ChangeRequest, cid))


async def test_toolshop_sees_no_prices_and_is_no_tool_engineer(session_factory, seed):
    cid = await _member_of(session_factory, seed, "Toolshop")
    async with session_factory() as s:
        eng = await s.get(User, seed["engineer_id"])
        assert not await PriceViewer(s, eng).may_read(await s.get(ChangeRequest, cid))
        assert not await can_edit_tools(s, eng)
