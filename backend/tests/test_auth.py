"""Auth and user management tests."""
from tests.conftest import ADMIN_PASSWORD, ENGINEER_PASSWORD


async def test_login_success(client):
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "eng@test.io", "password": ENGINEER_PASSWORD},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "engineer"
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_wrong_password(client):
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "eng@test.io", "password": "nope-nope-nope"},
    )
    assert res.status_code == 401


async def test_login_unknown_email_same_error(client):
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@test.io", "password": "whatever-123"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid credentials"


async def test_login_inactive_user_forbidden(client):
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@test.io", "password": "ghost-secret-1"},
    )
    assert res.status_code == 403


async def test_me(client, eng_auth):
    res = await client.get("/api/v1/auth/me", headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["email"] == "eng@test.io"
    assert res.json()["role"] == "engineer"


async def test_me_requires_token(client):
    res = await client.get("/api/v1/auth/me")
    assert res.status_code in (401, 403)


async def test_refresh_token(client):
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "eng@test.io", "password": ENGINEER_PASSWORD},
    )
    refresh = res.json()["refresh_token"]
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 200
    assert res.json()["access_token"]


async def test_change_password_roundtrip(client, eng_auth):
    res = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": ENGINEER_PASSWORD, "new_password": "brand-new-pass-1"},
        headers=eng_auth,
    )
    assert res.status_code == 200

    # Old password no longer works, new one does
    res = await client.post(
        "/api/v1/auth/login", json={"email": "eng@test.io", "password": ENGINEER_PASSWORD}
    )
    assert res.status_code == 401
    res = await client.post(
        "/api/v1/auth/login", json={"email": "eng@test.io", "password": "brand-new-pass-1"}
    )
    assert res.status_code == 200


async def test_users_requires_admin(client, eng_auth):
    res = await client.get("/api/v1/users", headers=eng_auth)
    assert res.status_code == 403


async def test_admin_creates_user_who_can_login(client, admin_auth):
    res = await client.post(
        "/api/v1/users",
        json={
            "email": "new@test.io",
            "username": "newbie",
            "full_name": "New User",
            "password": "newbie-pass-1",
            "role": "viewer",
        },
        headers=admin_auth,
    )
    assert res.status_code == 201, res.text

    res = await client.post(
        "/api/v1/auth/login", json={"email": "new@test.io", "password": "newbie-pass-1"}
    )
    assert res.status_code == 200
    assert res.json()["role"] == "viewer"


async def test_duplicate_email_conflict(client, admin_auth):
    res = await client.post(
        "/api/v1/users",
        json={
            "email": "eng@test.io",
            "username": "other",
            "password": "whatever-1234",
            "role": "viewer",
        },
        headers=admin_auth,
    )
    assert res.status_code == 409


async def test_admin_cannot_deactivate_self(client, admin_auth, seed):
    res = await client.patch(
        f"/api/v1/users/{seed['admin_id']}",
        json={"is_active": False},
        headers=admin_auth,
    )
    assert res.status_code == 400


async def test_deactivated_user_cannot_login(client, admin_auth, seed):
    res = await client.patch(
        f"/api/v1/users/{seed['engineer_id']}",
        json={"is_active": False},
        headers=admin_auth,
    )
    assert res.status_code == 200
    res = await client.post(
        "/api/v1/auth/login", json={"email": "eng@test.io", "password": ENGINEER_PASSWORD}
    )
    assert res.status_code == 403
