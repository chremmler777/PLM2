"""Global search and open-task-count tests."""


async def test_search_finds_part_and_project(client, eng_auth, part):
    res = await client.get("/api/v1/search?q=hous", headers=eng_auth)
    assert res.status_code == 200
    body = res.json()
    assert any(p["name"] == "Housing" for p in body["parts"])
    assert body["parts"][0]["project_name"] == "Project"

    res = await client.get("/api/v1/search?q=proj", headers=eng_auth)
    assert any(p["code"] == "proj" for p in res.json()["projects"])


async def test_search_no_results(client, eng_auth):
    res = await client.get("/api/v1/search?q=zzzzzz", headers=eng_auth)
    assert res.status_code == 200
    assert res.json() == {"parts": [], "projects": []}


async def test_search_requires_min_length(client, eng_auth):
    res = await client.get("/api/v1/search?q=a", headers=eng_auth)
    assert res.status_code == 422


async def test_open_task_count_empty(client, eng_auth):
    res = await client.get("/api/v1/workflow-instances/open-task-count", headers=eng_auth)
    assert res.status_code == 200
    assert res.json() == {"count": 0}
