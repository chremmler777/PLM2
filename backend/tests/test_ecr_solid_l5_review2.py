"""ECR-solid lane L5 (assessment + costing) review fixes, loop 2.

- Department notices reach only active members in the change's
  organization (R23, R33).
- HARD #8 holds for the amount approved: costs finalized above it in
  costing withdraw the internal approval (R7, R25).
- The internal 'estimate low' task and notice go to the lead (PM without a
  lead), who may propose the Absorb and reads prices; the approver decides
  the Absorb on its own task (R5, R23).
"""
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeChangelog, ChangeRequest
from app.models.entities import Organization, User
from app.models.notification import Notification
from tests.conftest import make_department_member
from tests.test_ecr_solid_l5_review import _position, _set, _u, _user, cc  # noqa: F401

pytestmark = pytest.mark.asyncio
DUE = (datetime.utcnow() + timedelta(days=120)).isoformat()
REF = "Tool 3343 recut 2025, FZ 4.1k"


async def _bare_user(session_factory, key, org_id, *, active=True):
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        u = User(organization_id=org_id, username=f"l5b-{key}",
                 email=f"l5b-{key}@test.io", full_name=f"L5b {key}",
                 hashed_password=get_password_hash("l5-secret-12"),
                 role="engineer", is_active=active, mfa_enabled=False)
        s.add(u)
        await s.commit()
        return u.id


# --- R23/R33: department notices stay in the change's organization ----------

async def test_sales_notice_skips_other_orgs_and_inactive_accounts(
        client, cc, seed, session_factory):
    sales_id, _, _ = await _user(client, session_factory, seed, "sa", "Sales")
    async with session_factory() as s:
        other = Organization(name="Other Org", code="other-org", is_active=True)
        s.add(other)
        await s.commit()
        other_id = other.id
    elsewhere = await _bare_user(session_factory, "elsewhere", other_id)
    gone = await _bare_user(session_factory, "gone", seed["org_id"], active=False)
    for uid in (elsewhere, gone):
        await make_department_member(session_factory, uid, "Sales")
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                          estimate_check="pending")
    await _set(session_factory, cc["cid"], status="approved",
               quoted_at=datetime.utcnow(), sales_owner_id=None)
    res = await client.post(_u(cc["cid"], f"/costing/positions/{pid}/estimate-check"),
                            json={"verdict": "above", "over": 4200}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"estimate_low:{pid}"))).scalars().all()
    assert told == [sales_id]
