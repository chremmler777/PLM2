import pytest

from tests.conftest import record_proceed_meeting, lock_impact
from tests.conftest import satisfy_capture_gate

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
    # Complete the capture (description + attachment + required-by date) so the
    # block below is the feasibility gate, not the kickoff or deadline gate.
    await satisfy_capture_gate(client, eng_auth, cid)
    # captured -> scoping, then record a proceed meeting so the in_assessment
    # guard reaches the gate check (not the proceed-meeting guard).
    scop = await client.post(f"/api/v1/changes/{cid}/transition",
                             json={"to_status": "scoping"}, headers=eng_auth)
    assert scop.status_code == 200, scop.text
    await record_proceed_meeting(session_factory, cid, actor_id=seed["engineer_id"])
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
    await lock_impact(session_factory, cid)  # -> in_assessment hard gate
    ok = await client.post(f"/api/v1/changes/{cid}/transition",
                           json={"to_status": "in_assessment"}, headers=eng_auth)
    assert ok.status_code == 200, ok.text


async def test_gates_exist_from_creation_and_block_by_default(client, eng_auth, seed,
                                                              session_factory):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "hard", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    gates = (await client.get(f"/api/v1/changes/{cid}/gates", headers=eng_auth)).json()
    assert {g["gate_key"] for g in gates} == {"release"}
    # seeded undecided, not 'n/a': nobody has answered it yet
    assert all(g["decision"] is None and g["decided_at"] is None for g in gates)
    # feasibility is no longer pre-seeded; explicitly create the row (still 'na')
    # to exercise the same default-blocks behaviour
    await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                     json={"decision": "na"}, headers=eng_auth)
    # default 'na' blocks even when other guards would pass
    pres = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "PG-H1", "name": "x",
        "part_type": "sub_assembly", "data_classification": "confidential"},
        headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": pres.json()["id"]}, headers=eng_auth)
    await satisfy_capture_gate(client, eng_auth, cid)
    # captured -> scoping + proceed meeting so the other in_assessment guards pass
    scop = await client.post(f"/api/v1/changes/{cid}/transition",
                             json={"to_status": "scoping"}, headers=eng_auth)
    assert scop.status_code == 200, scop.text
    await record_proceed_meeting(session_factory, cid, actor_id=seed["engineer_id"])
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


async def _gate_change(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "g", "change_type": "physical_part",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    return res.json()["id"]


async def test_gate_rows_carry_the_deciders_name(client, eng_auth, seed):
    cid = await _gate_change(client, eng_auth, seed)
    put = await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                           json={"decision": "yes"}, headers=eng_auth)
    assert put.json()["decided_by_name"] == "Engineer"
    lst = (await client.get(f"/api/v1/changes/{cid}/gates", headers=eng_auth)).json()
    g = next(g for g in lst if g["gate_key"] == "feasibility")
    assert g["decided_by"] == seed["engineer_id"]
    assert g["decided_by_name"] == "Engineer"


@pytest.mark.parametrize("status", ["closed", "cancelled", "rejected"])
async def test_finished_change_refuses_gate_and_d1_edits(
        client, eng_auth, seed, session_factory, status):
    from app.models.change import ChangeRequest
    cid = await _gate_change(client, eng_auth, seed)
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status = status
        await s.commit()
    put = await client.put(f"/api/v1/changes/{cid}/gates/feasibility",
                           json={"decision": "yes"}, headers=eng_auth)
    assert put.status_code == 400 and status in put.json()["detail"]
    res = await client.patch(f"/api/v1/changes/{cid}", json={"car_line": "G65"},
                             headers=eng_auth)
    assert res.status_code == 400, res.text
    assert "D1" in res.json()["detail"] and "car_line" in res.json()["detail"]
    # resending an unchanged D1 value (the panel sends every field) is fine
    detail = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    res = await client.patch(f"/api/v1/changes/{cid}",
                             json={"car_line": detail.get("car_line")}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_detail_carries_part_labels_and_project_plant(client, eng_auth, seed, session_factory):
    from app.models.entities import Project
    cid = await _gate_change(client, eng_auth, seed)
    pres = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "PL-77", "name": "Bracket",
        "part_type": "sub_assembly", "data_classification": "confidential"}, headers=eng_auth)
    add = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                            json={"part_id": pres.json()["id"]}, headers=eng_auth)
    assert add.status_code == 200, add.text
    assert (add.json()["part_number"], add.json()["part_name"]) == ("PL-77", "Bracket")
    detail = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    item = detail["impacted_items"][0]
    assert (item["part_number"], item["part_name"]) == ("PL-77", "Bracket")
    async with session_factory() as s:
        plant_id = (await s.get(Project, seed["project_id"])).plant_id
    assert detail["project_plant_id"] == plant_id
