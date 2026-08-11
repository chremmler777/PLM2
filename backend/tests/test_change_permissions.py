"""GET /changes/permissions — the answer the StartChangeButton gates on. It
must match what POST /changes would actually do, including under acts-as."""
import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _sales(session_factory, seed, member_id=None) -> int:
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        dept = Department(name="Sales", flow_type="action", is_active=True,
                          can_start_change=True)
        s.add(dept)
        await s.flush()
        if member_id is not None:
            s.add(UserDepartment(user_id=member_id, department_id=dept.id))
        await s.commit()
        return dept.id


async def _can_start(client, headers) -> bool:
    res = await client.get("/api/v1/changes/permissions", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["can_start_change"]


async def test_permissions_follow_the_effective_actor(
        client, admin_auth, eng_auth, seed, session_factory):
    # a starter department exists, the engineer is not in it
    dept_id = await _sales(session_factory, seed)
    assert await _can_start(client, eng_auth) is False

    # ...and the same call under acts-as Sales says yes, matching the endpoint
    acting = {**admin_auth, "X-Acts-As-Department": str(dept_id)}
    assert await _can_start(client, acting) is True
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "gated", "reason": "r",
        "change_type": "physical_part"}, headers=acting)
    assert res.status_code == 200, res.text


async def test_sales_member_may_start(client, seed, session_factory):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="seller",
                 email="seller@test.io", full_name="Seller",
                 hashed_password=get_password_hash("seller-secret-1"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        uid = u.id
        await s.commit()
    await _sales(session_factory, seed, member_id=uid)
    auth = await login(client, "seller@test.io")
    assert await _can_start(client, auth) is True


async def test_permissions_is_not_read_as_a_change_id(client, eng_auth, seed):
    """Route order: /permissions must not be swallowed by /{change_id}."""
    res = await client.get("/api/v1/changes/permissions", headers=eng_auth)
    assert res.status_code == 200
    assert "can_start_change" in res.json()
