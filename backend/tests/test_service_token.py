"""Machine callers authenticate with `Authorization: Bearer <PLM2_SERVICE_TOKEN>`
and get a read-only principal — the same pattern TWOS exposes to PDB. Browsers
keep the hub JWT cookie; nothing about that path changes."""
import pytest

from app.core.config import get_settings

pytestmark = pytest.mark.asyncio

TOKEN = "test-service-token-123"


@pytest.fixture
def service_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "plm2_service_token", TOKEN)
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def no_service_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "plm2_service_token", "")


async def test_bearer_token_reads(client, seed, service_token):
    res = await client.get("/api/v1/auth/me", headers=service_token)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plm2_roles"] == ["plm2_Viewer"]
    assert body["is_real_admin"] is False

    res = await client.get("/api/v1/equipment", params={"tool_number": "0000"},
                           headers=service_token)
    assert res.status_code == 404, res.text   # authenticated; no such tool


async def test_bearer_token_is_read_only(client, seed, service_token):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "3454",
        "name": "x", "part_type": "purchased", "item_category": "tool",
    }, headers=service_token)
    assert res.status_code == 403
    assert "read-only" in res.json()["detail"].lower()


async def test_wrong_bearer_token_is_401(client, seed, service_token):
    res = await client.get("/api/v1/auth/me",
                           headers={"Authorization": "Bearer nope"})
    assert res.status_code == 401


async def test_bearer_without_configured_token_is_503(client, seed, no_service_token):
    """An empty PLM2_SERVICE_TOKEN must never match an empty bearer."""
    res = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer "})
    assert res.status_code == 503
    res = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer x"})
    assert res.status_code == 503


async def test_service_principal_is_one_stable_user(client, seed, service_token):
    first = (await client.get("/api/v1/auth/me", headers=service_token)).json()
    second = (await client.get("/api/v1/auth/me", headers=service_token)).json()
    assert first["user_id"] == second["user_id"]
    assert first["username"] == "plm2-service"


async def test_cookie_auth_still_works_alongside(client, seed, admin_auth, service_token):
    res = await client.get("/api/v1/auth/me", headers=admin_auth)
    assert res.status_code == 200
    assert res.json()["is_real_admin"] is True


async def test_service_token_cannot_act_as(client, seed, service_token):
    res = await client.get("/api/v1/auth/me",
                           headers={**service_token, "X-Acts-As-Department": "1"})
    assert res.status_code == 403
