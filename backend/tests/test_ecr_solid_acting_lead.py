"""ECR-solid C32: every lead right goes through holds_lead, so an admin who
leads a change and acts as a department is exactly that department: no
price view, no all-department costing or implementation view, no counter
price. Without acting, the lead keeps them."""
import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from app.services.costing_position_service import CostingPositionService
from app.services.implementation_service import ImplementationService
from app.services.negotiation_service import NegotiationService
from app.services.price_redaction import PriceViewer

pytestmark = pytest.mark.asyncio


async def _setup(session_factory, seed):
    async with session_factory() as s:
        dev = Department(name="Development", flow_type="action", is_active=True)
        s.add(dev); await s.flush()
        s.add(UserDepartment(user_id=seed["admin_id"], department_id=dev.id))
        c = ChangeRequest(change_number="CR-C32", project_id=seed["project_id"],
                          title="t", raised_by=seed["admin_id"],
                          lead_id=seed["admin_id"], status="in_implementation")
        s.add(c); await s.commit()
        return dev.id, c.id


async def test_lead_rights_follow_holds_lead(session_factory, seed):
    dev_id, cid = await _setup(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        user = (await s.execute(select(User).where(
            User.id == seed["admin_id"]))).scalar_one()
        user.acts_as_department_id = dev_id   # instance attribute, per request
        assert user.effective_role == "engineer"
        assert await PriceViewer(s, user).may_read(change) is False
        assert await NegotiationService.may_read(s, change, user) is False
        assert await CostingPositionService.readable_department_ids(
            s, change, user) == {dev_id}
        assert await ImplementationService.readable_department_ids(
            s, change, user) == {dev_id}


async def test_lead_without_acting_keeps_the_rights(session_factory, seed):
    _, cid = await _setup(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        eng = await s.get(User, seed["engineer_id"])
        change.lead_id = eng.id
        assert eng.effective_role == "engineer"
        assert await PriceViewer(s, eng).may_read(change) is True
        assert await NegotiationService.may_read(s, change, eng) is True
        assert await CostingPositionService.readable_department_ids(
            s, change, eng) is None
        assert await ImplementationService.readable_department_ids(
            s, change, eng) is None
