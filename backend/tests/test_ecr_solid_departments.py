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


async def test_one_price_rule_for_management(session_factory, seed):
    """The summation / counter-price rule (NegotiationService.may_read) is
    PriceViewer's: Management reads there too, Toolshop does not."""
    from app.services.negotiation_service import NegotiationService
    cid = await _member_of(session_factory, seed, "Management")
    async with session_factory() as s:
        eng = await s.get(User, seed["engineer_id"])
        change = await s.get(ChangeRequest, cid)
        assert await NegotiationService.may_read(s, change, eng)
    async with session_factory() as s:
        await s.execute(UserDepartment.__table__.delete())
        await s.commit()
    await _member_of(session_factory, seed, "Toolshop")
    async with session_factory() as s:
        eng = await s.get(User, seed["engineer_id"])
        assert not await NegotiationService.may_read(
            s, await s.get(ChangeRequest, cid), eng)


async def test_management_books_no_hours(session_factory, seed):
    """Management decides; it is never routed and gets no cost-sheet rate row."""
    from app.services.cost_sheet_service import routable_department_ids
    await _member_of(session_factory, seed, "Management")
    await _member_of(session_factory, seed, "Toolshop")
    async with session_factory() as s:
        names = set((await s.execute(select(Department.name).where(
            Department.id.in_(await routable_department_ids(s))))).scalars())
        assert "Toolshop" in names and "Management" not in names
