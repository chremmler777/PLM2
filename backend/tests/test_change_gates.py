import pytest
pytestmark = pytest.mark.asyncio


async def test_decide_gate_records_and_lists(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "g", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    put = await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                           json={"decision": "yes", "remark": "ok"}, headers=eng_auth)
    assert put.status_code == 200, put.text
    assert put.json()["decision"] == "yes"
    lst = await client.get(f"/api/v1/changes/{cid}/gates", headers=eng_auth)
    keys = {g["gate_key"]: g["decision"] for g in lst.json()}
    assert keys["feasibility"] == "yes"


async def test_gate_blocks_transition_until_yes(client, eng_auth, seed, session_factory):
    from sqlalchemy import select
    from app.models.part import Part
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "g2", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    # add an impacted item so the existing in_assessment guard passes
    pres = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "PG-1", "name": "x",
        "part_type": "sub_assembly", "data_classification": "confidential"}, headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": pres.json()["id"]}, headers=eng_auth)
    # set the feasibility gate to "no" -> transition must be blocked without justification
    await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                     json={"decision": "no"}, headers=eng_auth)
    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400
    assert "gate" in blocked.json()["detail"].lower()
    # flip to yes -> allowed
    await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                     json={"decision": "yes"}, headers=eng_auth)
    ok = await client.post(f"/api/v1/changes/{cid}/transition",
                           json={"to_status": "in_assessment"}, headers=eng_auth)
    assert ok.status_code == 200, ok.text
