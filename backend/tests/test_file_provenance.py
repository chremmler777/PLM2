"""File lists name who uploaded what: every attachment/file endpoint carries
uploaded_by + uploaded_by_name (and a timestamp), resolved in one batched
query rather than one lookup per row."""
import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_change_attachments_carry_the_uploader(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "prov", "reason": "r",
        "change_type": "physical_part"}, headers=eng_auth)
    cid = res.json()["id"]
    up = await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": ("spec.pdf", b"%PDF-1.4 x", "application/pdf")},
        headers=eng_auth)
    assert up.status_code in (200, 201), up.text

    detail = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    att = detail["attachments"][0]
    assert att["uploaded_by"] == seed["engineer_id"]
    assert att["uploaded_by_name"] == "Engineer"
    assert att["created_at"] is not None


async def test_revision_files_carry_the_uploader(client, eng_auth, seed, part):
    res = await client.get(
        f"/api/v1/parts/revisions/{part['revision_id']}/files", headers=eng_auth)
    assert res.status_code == 200, res.text
    # The shape is what matters here — an empty list still proves the endpoint
    # survives the batched-name path; upload one to assert the fields.
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"file_type": "document"}, headers=eng_auth)
    assert up.status_code in (200, 201), up.text
    rows = (await client.get(
        f"/api/v1/parts/revisions/{part['revision_id']}/files",
        headers=eng_auth)).json()
    assert rows
    assert rows[0]["uploaded_by"] == seed["engineer_id"]
    assert rows[0]["uploaded_by_name"] == "Engineer"
    assert rows[0]["uploaded_at"] is not None
