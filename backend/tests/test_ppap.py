"""PPAP (Quality module) tests."""


async def _create_ppap(client, eng_auth, revision_id, level=1):
    res = await client.post(
        f"/api/v1/quality/revisions/{revision_id}/ppap",
        json={"level": level, "customer": "OEM AG"},
        headers=eng_auth,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_ppap_checklist_created_with_level_requirements(client, eng_auth, part):
    ppap = await _create_ppap(client, eng_auth, part["revision_id"], level=1)
    assert ppap["status"] == "draft"
    assert len(ppap["elements"]) == 18
    required = [e["name"] for e in ppap["elements"] if e["required"]]
    # Level 1: lab documentation + PSW
    assert "Part Submission Warrant (PSW)" in required
    assert len(required) == 2
    assert ppap["progress"] == {"done": 0, "required": 2}


async def test_ppap_submit_requires_complete_elements(client, eng_auth, part):
    ppap = await _create_ppap(client, eng_auth, part["revision_id"], level=1)

    res = await client.post(f"/api/v1/quality/ppap/{ppap['id']}/submit", headers=eng_auth)
    assert res.status_code == 400
    assert "incomplete" in res.json()["detail"].lower() or "Required" in res.json()["detail"]

    # Complete the two required elements
    for e in ppap["elements"]:
        if e["required"]:
            res = await client.patch(
                f"/api/v1/quality/ppap/elements/{e['id']}",
                json={"status": "approved"},
                headers=eng_auth,
            )
            assert res.status_code == 200

    res = await client.post(f"/api/v1/quality/ppap/{ppap['id']}/submit", headers=eng_auth)
    assert res.status_code == 200
    assert res.json()["status"] == "submitted"


async def test_ppap_approval_flow_and_changelog(client, eng_auth, part):
    pid, rid = part["part_id"], part["revision_id"]
    ppap = await _create_ppap(client, eng_auth, rid, level=1)

    for e in ppap["elements"]:
        if e["required"]:
            await client.patch(
                f"/api/v1/quality/ppap/elements/{e['id']}", json={"status": "na"}, headers=eng_auth
            )
    await client.post(f"/api/v1/quality/ppap/{ppap['id']}/submit", headers=eng_auth)

    # Approve only works on submitted; elements become read-only after decision
    res = await client.post(
        f"/api/v1/quality/ppap/{ppap['id']}/approve",
        json={"notes": "released"},
        headers=eng_auth,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "approved"

    element_id = ppap["elements"][0]["id"]
    res = await client.patch(
        f"/api/v1/quality/ppap/elements/{element_id}", json={"status": "approved"}, headers=eng_auth
    )
    assert res.status_code == 409

    res = await client.get(f"/api/v1/parts/{pid}/changelog", headers=eng_auth)
    actions = [e["action"] for e in res.json()]
    assert "ppap_created" in actions
    assert "ppap_submitted" in actions
    assert "ppap_approved" in actions


async def test_ppap_duplicate_open_submission_rejected(client, eng_auth, part):
    await _create_ppap(client, eng_auth, part["revision_id"])
    res = await client.post(
        f"/api/v1/quality/revisions/{part['revision_id']}/ppap",
        json={"level": 3},
        headers=eng_auth,
    )
    assert res.status_code == 409


async def test_ppap_element_file_must_belong_to_revision(client, eng_auth, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid, rid = part["part_id"], part["revision_id"]
    ppap = await _create_ppap(client, eng_auth, rid)

    # Upload evidence to this revision and attach it
    res = await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/files",
        files={"file": ("psw.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=eng_auth,
    )
    file_id = res.json()["id"]

    element_id = ppap["elements"][0]["id"]
    res = await client.patch(
        f"/api/v1/quality/ppap/elements/{element_id}",
        json={"file_id": file_id},
        headers=eng_auth,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "attached"  # auto-marked from pending

    # A bogus file id is rejected
    res = await client.patch(
        f"/api/v1/quality/ppap/elements/{element_id}",
        json={"file_id": 99999},
        headers=eng_auth,
    )
    assert res.status_code == 400


async def test_ppap_get_latest(client, eng_auth, part):
    res = await client.get(
        f"/api/v1/quality/revisions/{part['revision_id']}/ppap", headers=eng_auth
    )
    assert res.status_code == 200
    assert res.json() is None

    await _create_ppap(client, eng_auth, part["revision_id"])
    res = await client.get(
        f"/api/v1/quality/revisions/{part['revision_id']}/ppap", headers=eng_auth
    )
    assert res.json()["status"] == "draft"
