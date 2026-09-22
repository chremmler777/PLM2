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
