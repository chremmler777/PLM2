async def test_projects_list_carries_customer_naming(client, eng_auth, seed):
    rows = (await client.get("/api/v1/plants/projects", headers=eng_auth)).json()
    me = next(r for r in rows if r["id"] == seed["project_id"])
    assert me["customer_naming"] is None


async def test_patch_project_sets_customer_naming(client, eng_auth, seed):
    pid = seed["project_id"]
    r = await client.patch(f"/api/v1/plants/projects/{pid}", json={"customer_naming": "vw"}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["customer_naming"] == "vw"
    rows = (await client.get("/api/v1/plants/projects", headers=eng_auth)).json()
    assert next(x for x in rows if x["id"] == pid)["customer_naming"] == "vw"


async def test_patch_project_rejects_unknown_convention(client, eng_auth, seed):
    r = await client.patch(f"/api/v1/plants/projects/{seed['project_id']}",
                           json={"customer_naming": "bmw"}, headers=eng_auth)
    assert r.status_code == 422


async def test_patch_project_clears_customer_naming(client, eng_auth, seed):
    pid = seed["project_id"]
    await client.patch(f"/api/v1/plants/projects/{pid}", json={"customer_naming": "vw"}, headers=eng_auth)
    r = await client.patch(f"/api/v1/plants/projects/{pid}", json={"customer_naming": None}, headers=eng_auth)
    assert r.status_code == 200
    assert r.json()["customer_naming"] is None


async def test_patch_unknown_project_is_404(client, eng_auth):
    r = await client.patch("/api/v1/plants/projects/999999", json={"customer_naming": "vw"}, headers=eng_auth)
    assert r.status_code == 404


async def test_patch_project_null_name_leaves_name_unchanged(client, eng_auth, seed):
    pid = seed["project_id"]
    r = await client.patch(f"/api/v1/plants/projects/{pid}", json={"name": None}, headers=eng_auth)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Project"


async def test_patch_project_rejects_junk_status(client, eng_auth, seed):
    r = await client.patch(f"/api/v1/plants/projects/{seed['project_id']}",
                           json={"status": "banana"}, headers=eng_auth)
    assert r.status_code == 422


async def test_patch_project_rejects_overlong_name(client, eng_auth, seed):
    r = await client.patch(f"/api/v1/plants/projects/{seed['project_id']}",
                           json={"name": "x" * 256}, headers=eng_auth)
    assert r.status_code == 422


async def test_patch_project_forbidden_for_viewer(client, eng_auth, session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User

    async with session_factory() as s:
        viewer = User(
            organization_id=seed["org_id"], username="viewer", email="viewer@test.io",
            full_name="Viewer", hashed_password=get_password_hash("viewer-secret-1"),
            role="viewer", is_active=True, mfa_enabled=False,
        )
        s.add(viewer)
        await s.commit()

    from tests.conftest import login
    viewer_auth = await login(client, "viewer@test.io", "viewer-secret-1")
    r = await client.patch(f"/api/v1/plants/projects/{seed['project_id']}",
                           json={"customer_naming": "vw"}, headers=viewer_auth)
    assert r.status_code == 403
