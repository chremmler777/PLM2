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
    # set the feasibility gate to "no" -> transition must be blocked without an approved deviation
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


async def test_gates_exist_from_creation_and_block_by_default(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "hard", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    gates = (await client.get(f"/api/v1/changes/{cid}/gates", headers=eng_auth)).json()
    assert {g["gate_key"] for g in gates} == {"feasibility", "budget", "release"}
    assert all(g["decision"] == "na" for g in gates)
    # default 'na' blocks even when other guards would pass
    pres = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "PG-H1", "name": "x",
        "part_type": "sub_assembly", "data_classification": "confidential"},
        headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": pres.json()["id"]}, headers=eng_auth)
    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400
    assert "gate" in blocked.json()["detail"].lower()


async def test_gate_decide_requires_lead_or_admin(client, eng_auth, admin_auth, seed):
    # lead is the ADMIN here, so the engineer must be rejected
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "authz", "change_type": "physical_part",
        "lead_id": seed["admin_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    denied = await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                              json={"decision": "yes"}, headers=eng_auth)
    assert denied.status_code == 403
    ok = await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                          json={"decision": "yes"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text
