"""Acting as a department drops the change-lead right on every write rule
(roles audit issue 6), not only on the gates and deviations: the frontend
already drops it (isChangeLead = !actingAs ...), so the backend must too.

Spec: docs/superpowers/specs/2026-07-22-acts-as-role-switch-design.md (D2);
the one rule is change_people.holds_lead.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.entities import User
from app.models.workflow import Department
from app.services.change_plan_service import ChangePlanService
from app.services.change_service import ChangeService
from app.services.release_service import ReleaseService

pytestmark = pytest.mark.asyncio


async def _admin_lead(session_factory, seed, acting: bool):
    """The seeded admin, leading a change; optionally acting as an unrelated department."""
    s = session_factory()
    admin = (await s.execute(select(User).where(User.id == seed["admin_id"]))).scalar_one()
    if acting:
        d = Department(name="Unrelated", flow_type="action", is_active=True)
        s.add(d)
        await s.flush()
        admin.acts_as_department_id = d.id
    change = SimpleNamespace(id=0, lead_id=admin.id)
    return s, admin, change


RULES = [
    ("quoted price", lambda s, u, c: ChangeService.user_can_set_quoted_price(s, u, c)),
    ("bank build", lambda s, u, c: ChangeService.user_can_decide_bank_build(s, u, c)),
    ("release", lambda s, u, c: ReleaseService.is_pm_or_lead(s, c, u)),
    ("plan editor", lambda s, u, c: ChangePlanService.is_editor(s, c, u)),
    ("plan deviation", lambda s, u, c: ChangePlanService.may_decide_deviation(s, c, u)),
]


@pytest.mark.parametrize("name,rule", RULES, ids=[r[0] for r in RULES])
async def test_acting_lead_loses_the_lead_right(session_factory, seed, name, rule):
    s, admin, change = await _admin_lead(session_factory, seed, acting=True)
    try:
        assert await rule(s, admin, change) is False, name
    finally:
        await s.close()


@pytest.mark.parametrize("name,rule", RULES, ids=[r[0] for r in RULES])
async def test_lead_keeps_the_right_when_not_acting(session_factory, seed, name, rule):
    s, admin, change = await _admin_lead(session_factory, seed, acting=False)
    # Not an admin here: the plain lead right must still hold.
    admin_role, admin.role = admin.role, "engineer"
    try:
        assert await rule(s, admin, change) is True, name
    finally:
        admin.role = admin_role
        await s.rollback()
        await s.close()


async def test_non_lead_engineer_gets_nothing(session_factory, seed):
    s = session_factory()
    try:
        eng = (await s.execute(select(User).where(User.id == seed["engineer_id"]))).scalar_one()
        change = SimpleNamespace(id=0, lead_id=seed["admin_id"])
        for name, rule in RULES:
            assert await rule(s, eng, change) is False, name
    finally:
        await s.close()
