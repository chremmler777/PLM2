"""Department membership from AdminPanel (migration 150): a hub account is a
member of exactly the active departments whose hub_role its token carries,
synced at login (written only when it differs); plm2_Viewer alone is no
member; plm2_Admin with department roles is admin AND member; local
accounts keep their stored memberships; the per-user PUT refuses hub
accounts (409)."""
from datetime import datetime, timedelta

import pytest
from jose import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from app.services.hub_departments import sync_memberships
from tests.conftest import login

pytestmark = pytest.mark.asyncio


def _cookie(username: str, *roles: str) -> dict:
    s = get_settings()
    token = jwt.encode({"sub": "9", "username": username,
                        "roles": [{"name": r, "system": s.role_system} for r in roles],
                        "exp": datetime.utcnow() + timedelta(hours=1)},
                       s.jwt_secret, algorithm=s.jwt_algorithm)
    return {"Cookie": f"{s.jwt_cookie_name}={token}"}


async def _depts(session_factory):
    async with session_factory() as s:
        out = {}
        for name, role in (("Sales", "plm2_Sales"), ("Quality", "plm2_Quality"),
                           ("Development", "plm2_Development"), ("Legacy", None)):
            d = Department(name=name, flow_type="action", is_active=True, hub_role=role)
            s.add(d); await s.flush(); out[name] = d.id
        await s.commit()
        return out


async def _state(session_factory, username):
    async with session_factory() as s:
        u = (await s.execute(select(User).where(User.username == username))).scalar_one()
        ids = set((await s.execute(select(UserDepartment.department_id).where(
            UserDepartment.user_id == u.id))).scalars().all())
        return u, ids


async def _hit(client, cookie):
    res = await client.get("/api/v1/departments/overview", headers=cookie)
    assert res.status_code == 200, res.text


async def test_login_adds_and_removes_departments_from_the_token(client, session_factory, seed):
    d = await _depts(session_factory)
    await _hit(client, _cookie("karl.limburg", "plm2_Sales", "plm2_Viewer"))
    u, ids = await _state(session_factory, "karl.limburg")
    assert u.hashed_password == "!" and ids == {d["Sales"]} and u.role == "engineer"
    await _hit(client, _cookie("karl.limburg", "plm2_Quality"))
    _, ids = await _state(session_factory, "karl.limburg")
    assert ids == {d["Quality"]}


async def test_unchanged_roles_write_nothing(client, session_factory, seed):
    d = await _depts(session_factory)
    await _hit(client, _cookie("jubei.hughes", "plm2_Sales"))
    u, _ = await _state(session_factory, "jubei.hughes")
    async with session_factory() as s:
        ids, changed = await sync_memberships(s, u.id, ["plm2_Sales"])
        assert ids == {d["Sales"]} and changed is False
        assert not s.new and not s.dirty and not s.deleted


async def test_viewer_only_is_no_member_and_read_only(client, session_factory, seed):
    d = await _depts(session_factory)
    await _hit(client, _cookie("roman.somin", "plm2_Sales"))
    await _hit(client, _cookie("roman.somin", "plm2_Viewer"))
    u, ids = await _state(session_factory, "roman.somin")
    assert ids == set() and u.role == "viewer"
    assert d  # departments exist, none granted


async def test_admin_with_department_roles_is_admin_and_member(client, session_factory, seed):
    d = await _depts(session_factory)
    await _hit(client, _cookie("christoph.demmler", "plm2_Admin", "plm2_Development", "plm2_Quality"))
    u, ids = await _state(session_factory, "christoph.demmler")
    assert u.role == "admin" and ids == {d["Development"], d["Quality"]}


async def test_retired_or_unmapped_departments_are_not_granted(client, session_factory, seed):
    d = await _depts(session_factory)
    async with session_factory() as s:
        (await s.get(Department, d["Quality"])).is_active = False
        await s.commit()
    await _hit(client, _cookie("alexa.earls", "plm2_Quality", "plm2_Sales"))
    _, ids = await _state(session_factory, "alexa.earls")
    assert ids == {d["Sales"]}


async def test_local_accounts_keep_their_stored_memberships(client, session_factory, seed):
    d = await _depts(session_factory)
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=d["Legacy"]))
        await s.commit()
    await _hit(client, _cookie("eng", "plm2_Sales"))       # the seeded local engineer
    async with session_factory() as s:
        ids = set((await s.execute(select(UserDepartment.department_id).where(
            UserDepartment.user_id == seed["engineer_id"]))).scalars().all())
    assert ids == {d["Legacy"]}


async def test_per_user_put_refuses_hub_accounts(client, session_factory, seed):
    d = await _depts(session_factory)
    await _hit(client, _cookie("cory.mccall", "plm2_Sales"))
    u, _ = await _state(session_factory, "cory.mccall")
    admin = await login(client, "admin@test.io")
    res = await client.put(f"/api/v1/users/{u.id}/departments", headers=admin,
                           json={"department_ids": [d["Quality"]]})
    assert res.status_code == 409 and "AdminPanel" in res.json()["detail"]


async def test_sync_can_be_switched_off(client, session_factory, seed, monkeypatch):
    d = await _depts(session_factory)
    await _hit(client, _cookie("dale.perry", "plm2_Sales"))
    monkeypatch.setattr(get_settings(), "hub_department_sync", False)
    await _hit(client, _cookie("dale.perry", "plm2_Quality"))
    _, ids = await _state(session_factory, "dale.perry")
    assert ids == {d["Sales"]}
