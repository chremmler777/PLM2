import pytest
from tests.conftest import _mint_cookie


@pytest.mark.asyncio
async def test_me_returns_identity_and_plm2_roles(client, seed):
    r = await client.get("/api/v1/auth/me", headers=_mint_cookie("admin@test.io"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plm2_roles"] == ["plm2_Admin"]
    assert body["system"] == "plm2"


@pytest.mark.asyncio
async def test_missing_cookie_401(client, seed):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_no_plm2_role_403(client, seed):
    from datetime import datetime, timedelta
    from jose import jwt
    from app.core.config import get_settings
    s = get_settings()
    token = jwt.encode(
        {"sub": "1", "email": "admin@test.io", "roles": [{"name": "kpi_Viewer", "system": "kpi"}],
         "exp": datetime.utcnow() + timedelta(hours=1)},
        s.jwt_secret, algorithm=s.jwt_algorithm)
    r = await client.get("/api/v1/auth/me", headers={"Cookie": f"{s.jwt_cookie_name}={token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_viewer_is_read_only(client, seed):
    # A GET is allowed; a mutating method is 403 for a viewer cookie.
    # /api/v1/projects doesn't exist (routes are under /api/v1/plants/projects);
    # use that existing GET+POST pair so the probe actually exercises the gate.
    ok = await client.get("/api/v1/plants/projects", headers=_mint_cookie("admin@test.io", admin=False))
    assert ok.status_code in (200, 404)  # route exists / empty, but NOT 403
    blocked = await client.post("/api/v1/plants/projects", json={},
                                headers=_mint_cookie("admin@test.io", admin=False))
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_unknown_email_is_auto_provisioned(client, seed, session_factory):
    from sqlalchemy import select
    from app.models.entities import User
    r = await client.get("/api/v1/auth/me", headers=_mint_cookie("newhub@ktx.io"))
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        u = (await s.execute(select(User).where(User.email == "newhub@ktx.io"))).scalar_one()
        assert u.role == "admin"
        assert u.hashed_password == "!"
