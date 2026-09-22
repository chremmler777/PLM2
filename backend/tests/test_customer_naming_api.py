"""HTTP flow: parse endpoint for upload filenames, and package preview
reading the project's customer naming convention."""


async def _mk_part(client, auth, seed, number, customer_number):
    r = await client.post("/api/v1/parts", headers=auth, json={
        "project_id": seed["project_id"], "part_number": number, "name": number,
        "part_type": "internal_mfg", "data_classification": "confidential",
        "customer_part_number": customer_number})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_parse_uses_project_convention_by_default(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, "20-1", "206.881.479")
    await client.patch(f"/api/v1/plants/projects/{seed['project_id']}", json={"customer_naming": "vw"}, headers=eng_auth)
    r = await client.get(f"/api/v1/parts/{pid}/files/parse", headers=eng_auth, params={
        "filenames": ["206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528.CATPart",
                      "readme.txt"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["convention"] == "vw"
    assert body["conventions"] == {"vw": "VW group", "scout": "Scout"}
    assert body["rows"][0]["customer_index"] == "003"
    assert body["rows"][0]["kind"] == "PCA"
    assert body["rows"][0]["dated"] == "2026-05-28"
    assert body["rows"][1]["customer_index"] is None


async def test_parse_override_and_none(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, "20-2", "3CR.807.425")
    r = await client.get(f"/api/v1/parts/{pid}/files/parse", headers=eng_auth, params={
        "filenames": ["3CR807425B_x.stp"], "convention": "none"})
    assert r.json()["convention"] is None
    assert r.json()["rows"][0]["customer_index"] == "B"
    r = await client.get(f"/api/v1/parts/{pid}/files/parse", headers=eng_auth, params={
        "filenames": ["206_881_479____DMU_TM__003_____X___B-RELEASE___20260528.CATPart"], "convention": "vw"})
    assert r.json()["rows"][0]["customer_index"] == "003"


async def test_parse_rejects_unknown_convention(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, "20-3", None)
    r = await client.get(f"/api/v1/parts/{pid}/files/parse", headers=eng_auth,
                         params={"filenames": ["a.stp"], "convention": "bmw"})
    assert r.status_code == 422


async def test_package_preview_reads_vw_index_when_project_set(client, eng_auth, seed):
    top = await _mk_part(client, eng_auth, seed, "20-10", "206.881.971")
    child = await _mk_part(client, eng_auth, seed, "20-11", "206.881.479")
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-data", headers=eng_auth,
                          json={"statement": "review", "received_at": "2026-05-01", "customer_index": "A"})
    assert r.status_code == 201, r.text
    top_rev = r.json()["id"]
    r = await client.post(f"/api/v1/parts/{top}/revisions/{top_rev}/bom", headers=eng_auth,
                          json={"child_part_id": child, "quantity": 1, "unit": "pcs"})
    assert r.status_code in (200, 201), r.text
    await client.patch(f"/api/v1/plants/projects/{seed['project_id']}", json={"customer_naming": "vw"}, headers=eng_auth)

    files = [("files", ("206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528.stp",
                        b"ISO-10303-21;", "model/step"))]
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-package/preview", headers=eng_auth,
                          data={"statement": "review", "received_at": "2026-05-28"}, files=files)
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert row["part_id"] == child
    assert row["customer_index"] == "003"
