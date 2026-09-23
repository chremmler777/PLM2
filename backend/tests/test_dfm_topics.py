"""DFM topics on a tool: open, list, close (finished confirmed), reopen.
Only tools have an archive."""


async def make_tool(client, eng_auth, seed, number="199403", item_category="tool"):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": "ISOFIX Cover",
        "part_type": "purchased", "data_classification": "confidential", "item_category": item_category,
    }, headers=eng_auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_open_list_close_reopen(client, eng_auth, seed):
    tool = await make_tool(client, eng_auth, seed)

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)
    assert res.status_code == 200 and res.json() == []

    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics", json={"title": "Gate position"}, headers=eng_auth)
    assert res.status_code == 201, res.text
    topic = res.json()
    assert topic["status"] == "open"
    assert topic["title"] == "Gate position"
    assert topic["opened_by"] == seed["engineer_id"]
    assert topic["entry_count"] == 0
    assert topic["last_activity"] == topic["opened_at"]
    assert topic["closed_at"] is None

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)
    assert [t["id"] for t in res.json()] == [topic["id"]]

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic['id']}", headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["entries"] == []

    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic['id']}/close", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "finished_confirmed"
    assert res.json()["closed_by"] == seed["engineer_id"]
    assert res.json()["closed_at"] is not None

    # closing twice is a no-op conflict
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic['id']}/close", headers=eng_auth)
    assert res.status_code == 409

    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic['id']}/reopen", headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["status"] == "open"
    assert res.json()["closed_at"] is None

    res = await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)
    actions = [e["action"] for e in res.json()]
    assert actions.count("dfm_topic_opened") == 1
    assert actions.count("dfm_topic_closed") == 1
    assert actions.count("dfm_topic_reopened") == 1


async def test_title_required(client, eng_auth, seed):
    tool = await make_tool(client, eng_auth, seed)
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics", json={"title": "   "}, headers=eng_auth)
    assert res.status_code == 422


async def test_dfm_only_on_tools(client, eng_auth, seed):
    article = await make_tool(client, eng_auth, seed, number="20-1994-003-0", item_category="article")
    res = await client.get(f"/api/v1/parts/{article}/dfm/topics", headers=eng_auth)
    assert res.status_code == 400
    assert res.json()["detail"] == "Only tools have a DFM archive"
    res = await client.post(f"/api/v1/parts/{article}/dfm/topics", json={"title": "x"}, headers=eng_auth)
    assert res.status_code == 400
    res = await client.get("/api/v1/parts/999999/dfm/topics", headers=eng_auth)
    assert res.status_code == 404


async def test_topic_belongs_to_its_tool(client, eng_auth, seed):
    tool_a = await make_tool(client, eng_auth, seed, number="199403")
    tool_b = await make_tool(client, eng_auth, seed, number="199404")
    topic = (await client.post(f"/api/v1/parts/{tool_a}/dfm/topics", json={"title": "Gate"}, headers=eng_auth)).json()
    res = await client.get(f"/api/v1/parts/{tool_b}/dfm/topics/{topic['id']}", headers=eng_auth)
    assert res.status_code == 404


async def test_requires_login(client, seed, eng_auth):
    tool = await make_tool(client, eng_auth, seed)
    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics")
    assert res.status_code == 401
