async def _create(client, auth, seed, number, name, item_category="article"):
    res = await client.post("/api/v1/parts", headers=auth, json={
        "project_id": seed["project_id"], "part_number": number, "name": name,
        "part_type": "internal_mfg", "data_classification": "confidential", "item_category": item_category,
        "customer_part_number": f"C-{number}"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _customer_data(client, auth, pid, index):
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=auth,
                          json={"statement": "review", "received_at": "2026-05-28", "customer_index": index})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_structure_lists_articles_with_revisions_related_and_mirrors(client, eng_auth, seed):
    lh = await _create(client, eng_auth, seed, "20-1", "Handle LH")
    rh = await _create(client, eng_auth, seed, "20-2", "Handle RH")
    tool = await _create(client, eng_auth, seed, "T-1", "Tool", "tool")
    e1 = await _customer_data(client, eng_auth, lh, "003")
    r = await client.post(f"/api/v1/parts/{lh}/revisions/proposals", headers=eng_auth,
                          json={"parent_revision_id": e1, "summary": "investigation"})
    assert r.status_code in (200, 201), r.text
    for target in (lh, rh):
        assert (await client.post(f"/api/v1/parts/{tool}/relations", headers=eng_auth,
                                  json={"to_part_id": target, "relation_type": "produces"})).status_code == 201
    assert (await client.post(f"/api/v1/parts/{rh}/relations", headers=eng_auth,
                              json={"to_part_id": lh, "relation_type": "mirror_of"})).status_code == 201

    res = await client.get(f"/api/v1/parts/project/{seed['project_id']}/structure", headers=eng_auth)
    assert res.status_code == 200, res.text
    arts = {a["part_number"]: a for a in res.json()["articles"]}
    assert list(arts) == ["20-1", "20-2"]  # the tool is not an article
    a = arts["20-1"]
    assert [(x["revision_name"], x["customer_index"], x["parent_revision_id"] is None, x["is_active"]) for x in a["revisions"]] == [
        ("E1", "003", True, True), ("E1.1", None, False, False)]
    assert [(x["label"], x["part_number"], x["item_category"]) for x in a["related"]] == [("produced by", "T-1", "tool")]
    assert a["mirror_of"] is None
    assert [m["part_number"] for m in a["mirrored_by"]] == ["20-2"]
    b = arts["20-2"]
    assert b["mirror_of"]["part_number"] == "20-1"
    assert b["mirror_of"]["customer_part_number"] == "C-20-1"
    assert b["mirrored_by"] == []
    assert b["revisions"] == []


async def test_structure_unknown_project_is_empty(client, eng_auth):
    res = await client.get("/api/v1/parts/project/999999/structure", headers=eng_auth)
    assert res.status_code == 200
    assert res.json() == {"articles": []}


async def test_structure_query_count_is_bounded(client, eng_auth, seed, session_factory):
    from sqlalchemy import event
    for i in range(6):
        pid = await _create(client, eng_auth, seed, f"20-{i}", f"P{i}")
        await _customer_data(client, eng_auth, pid, "001")
    count = {"n": 0}
    def _count(*_a, **_k):
        count["n"] += 1
    sync_engine = session_factory.kw["bind"].sync_engine
    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        res = await client.get(f"/api/v1/parts/project/{seed['project_id']}/structure", headers=eng_auth)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)
    assert res.status_code == 200
    assert count["n"] <= 6, count  # auth lookup + ≤ 4 structure queries + slack
