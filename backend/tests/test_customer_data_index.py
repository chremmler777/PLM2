"""HTTP flow: customer data → E1/E2 → official 1 → proposal 1.1 → promote."""
from tests.conftest import login


async def _mk_part(client, auth, seed, number="P-CD"):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": "Panel",
        "part_type": "internal_mfg", "data_classification": "confidential"}, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def test_customer_data_flow(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed)
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-01", "customer_index": "A"})
    assert r.status_code == 201, r.text
    e1 = r.json()
    assert e1["revision_name"] == "E1" and e1["phase"] == "review" and e1["source"] == "customer"
    assert e1["customer_index"] == "A" and e1["part_phase_at_receipt"] == "rfq"

    r = await client.post(f"/api/v1/parts/{pid}/revisions/proposals", headers=eng_auth,
                          json={"parent_revision_id": e1["id"], "summary": "our tweak"})
    assert r.status_code == 201 and r.json()["revision_name"] == "E1.1"

    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "official", "received_at": "2026-09-10", "customer_index": "B"})
    assert r.status_code == 201 and r.json()["revision_name"] == "1"

    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-11"})
    assert r.status_code == 409

    part = (await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)).json()
    assert [x["revision_name"] for x in part["revisions"]] == ["E1", "E1.1", "1"]
    assert part["active_revision_id"] == [x for x in part["revisions"] if x["revision_name"] == "1"][0]["id"]


async def test_promote_needs_statement(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed)
    e1 = (await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                            json={"statement": "review", "received_at": "2026-09-01"})).json()
    p = (await client.post(f"/api/v1/parts/{pid}/revisions/proposals", headers=eng_auth,
                           json={"parent_revision_id": e1["id"]})).json()
    r = await client.post(f"/api/v1/parts/{pid}/revisions/{p['id']}/promote", headers=eng_auth, json={})
    assert r.status_code == 422
    r = await client.post(f"/api/v1/parts/{pid}/revisions/{p['id']}/promote", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-05"})
    assert r.status_code == 200 and r.json()["revision_name"] == "E2"


async def test_lifecycle_phase_admin_only(client, eng_auth, admin_auth, seed):
    pid = await _mk_part(client, eng_auth, seed)
    viewer = await login(client, "eng@test.io", admin=False)
    r = await client.post(f"/api/v1/parts/{pid}/lifecycle-phase", headers=viewer,
                          json={"phase": "nominated", "effective": "2026-09-01"})
    assert r.status_code == 403, r.text
    r = await client.post(f"/api/v1/parts/{pid}/lifecycle-phase", headers=admin_auth,
                          json={"phase": "nominated", "effective": "2026-09-01"})
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle_phase"] == "nominated" and r.json()["nominated_at"] == "2026-09-01"
    r = await client.post(f"/api/v1/parts/{pid}/lifecycle-phase", headers=admin_auth,
                          json={"phase": "nominated", "effective": "2026-09-02"})
    assert r.status_code == 400


async def test_legacy_endpoints_are_gone(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed)
    for path in ("revisions/rfq", "revisions/engineering", "revisions/freeze"):
        r = await client.post(f"/api/v1/parts/{pid}/{path}", headers=eng_auth, json={"summary": "x"})
        assert r.status_code in (404, 405), path


async def test_customer_data_with_chosen_major(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, number="P-CD-MAJ")
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-01", "major": 2})
    assert r.status_code == 201 and r.json()["revision_name"] == "E2"
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-09-02", "major": 2})
    assert r.status_code == 409
    assert "above E2" in r.json()["detail"]
