"""Auth and user management tests."""


async def test_me_requires_token(client):
    res = await client.get("/api/v1/auth/me")
    assert res.status_code in (401, 403)


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
