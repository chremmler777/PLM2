"""Who may write (roles audit issue 1, strategy B).

No new hub role: a non-admin hub user who belongs to at least one active PLM
department is a local 'engineer' and may write within the department gates.
Without a department they stay read-only viewers. plm2_Admin stays admin, and
only admins assign departments, so write access is granted in one place.

Engineers are not admins: no admin bypass, and admin-only configuration
(user departments, KPI targets, workflow templates, routing standards) stays
admin-only.
"""
from datetime import datetime, timedelta

import pytest
from jose import jwt as _jwt
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from tests.conftest import _mint_cookie

pytestmark = pytest.mark.asyncio


def _hub_cookie(email: str, *hub_roles: str) -> dict:
    s = get_settings()
    token = _jwt.encode(
        {"sub": "1", "email": email, "username": email.split("@")[0],
         "roles": [{"name": r, "system": s.role_system} for r in hub_roles],
         "exp": datetime.utcnow() + timedelta(hours=1)},
        s.jwt_secret, algorithm=s.jwt_algorithm)
    return {"Cookie": f"{s.jwt_cookie_name}={token}"}


async def _hub_user(client, session_factory, email, dept_active=None):
    """Provision a plm2_Viewer hub user; optionally put them in a new department."""
    r = await client.get("/api/v1/auth/me", headers=_hub_cookie(email, "plm2_Viewer"))
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        u = (await s.execute(select(User).where(User.email == email))).scalar_one()
        if dept_active is not None:
            d = Department(name=f"D-{email}", flow_type="action", is_active=dept_active)
            s.add(d)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=d.id))
        await s.commit()
        return u.id


async def _role(session_factory, email):
    async with session_factory() as s:
        return (await s.execute(select(User.role).where(User.email == email))).scalar_one()


async def _probe_write(client, email):
    """A POST past the read-only gate answers anything but the viewer 403."""
    r = await client.post("/api/v1/plants/projects", json={},
                          headers=_hub_cookie(email, "plm2_Viewer"))
    return "read-only" not in r.text


async def test_department_member_becomes_engineer_and_may_write(client, seed, session_factory):
    await _hub_user(client, session_factory, "member@ktx.io", dept_active=True)
    r = await client.get("/api/v1/auth/me", headers=_hub_cookie("member@ktx.io", "plm2_Viewer"))
    assert r.json()["effective_role"] == "engineer"
    assert r.json()["role"] == "engineer"
    assert await _role(session_factory, "member@ktx.io") == "engineer"
    assert await _probe_write(client, "member@ktx.io")


async def test_viewer_without_department_stays_read_only(client, seed, session_factory):
    await _hub_user(client, session_factory, "nodept@ktx.io")
    assert await _role(session_factory, "nodept@ktx.io") == "viewer"
    assert not await _probe_write(client, "nodept@ktx.io")


async def test_inactive_department_grants_nothing(client, seed, session_factory):
    await _hub_user(client, session_factory, "retired@ktx.io", dept_active=False)
    assert not await _probe_write(client, "retired@ktx.io")
    assert await _role(session_factory, "retired@ktx.io") == "viewer"


async def test_removing_the_department_takes_write_back(client, seed, session_factory):
    uid = await _hub_user(client, session_factory, "leaver@ktx.io", dept_active=True)
    assert await _probe_write(client, "leaver@ktx.io")
    async with session_factory() as s:
        await s.execute(delete(UserDepartment).where(UserDepartment.user_id == uid))
        await s.commit()
    assert not await _probe_write(client, "leaver@ktx.io")
    assert await _role(session_factory, "leaver@ktx.io") == "viewer"


async def test_engineer_hub_role_alone_grants_nothing(client, seed, session_factory):
    # No plm2_Engineer hub role exists on purpose: write comes from departments.
    r = await client.post("/api/v1/plants/projects", json={},
                          headers=_hub_cookie("hubeng@ktx.io", "plm2_Engineer"))
    assert r.status_code == 403


async def test_admin_stays_admin_without_departments(client, seed, session_factory):
    r = await client.get("/api/v1/auth/me", headers=_hub_cookie("hubadmin@ktx.io", "plm2_Admin"))
    assert r.json()["effective_role"] == "admin"


async def test_engineer_cannot_set_user_departments(client, seed, session_factory):
    await _hub_user(client, session_factory, "member@ktx.io", dept_active=True)
    r = await client.put(f"/api/v1/users/{seed['engineer_id']}/departments",
                         json={"department_ids": []},
                         headers=_hub_cookie("member@ktx.io", "plm2_Viewer"))
    assert r.status_code == 403, r.text


async def test_engineer_cannot_set_kpi_targets(client, seed, session_factory):
    await _hub_user(client, session_factory, "member@ktx.io", dept_active=True)
    r = await client.put("/api/v1/reports/ecr-kpis/targets", json={},
                         headers=_hub_cookie("member@ktx.io", "plm2_Viewer"))
    assert r.status_code == 403, r.text


async def test_engineer_cannot_edit_workflow_templates(client, seed, session_factory):
    await _hub_user(client, session_factory, "member@ktx.io", dept_active=True)
    h = _hub_cookie("member@ktx.io", "plm2_Viewer")
    r = await client.post("/api/v1/workflow-templates",
                          json={"name": "Sneaky", "stages": []}, headers=h)
    assert r.status_code == 403, r.text
    ok = await client.post("/api/v1/workflow-templates",
                           json={"name": "Legit", "stages": []},
                           headers=_mint_cookie("admin@test.io"))
    assert ok.status_code == 201, ok.text
    tid = ok.json()["id"]
    r = await client.put(f"/api/v1/workflow-templates/{tid}",
                         json={"name": "Sneaky", "stages": []}, headers=h)
    assert r.status_code == 403, r.text
    r = await client.delete(f"/api/v1/workflow-templates/{tid}", headers=h)
    assert r.status_code == 403, r.text


async def test_engineer_cannot_set_routing_standard(client, seed, session_factory):
    await _hub_user(client, session_factory, "member@ktx.io", dept_active=True)
    ok = await client.post("/api/v1/workflow-templates",
                           json={"name": "Std", "stages": []},
                           headers=_mint_cookie("admin@test.io"))
    tid = ok.json()["id"]
    r = await client.put("/api/v1/changes/routing-standards",
                         json={"change_type": "ecr", "template_id": tid},
                         headers=_hub_cookie("member@ktx.io", "plm2_Viewer"))
    assert r.status_code == 403, r.text
