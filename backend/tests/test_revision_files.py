"""Revision-scoped file management tests."""
import pytest

from tests.conftest import freeze_revision


def _upload(name: str, content: bytes = b"hello world"):
    return {"file": (name, content, "application/octet-stream")}


async def test_upload_list_download_delete(client, eng_auth, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # uploads land in tmp, not the repo
    pid, rid = part["part_id"], part["revision_id"]

    res = await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/files", files=_upload("spec.txt"), headers=eng_auth
    )
    assert res.status_code == 201, res.text
    body = res.json()
    file_id = body["id"]
    assert body["file_type"] == "document"
    assert body["has_viewer"] is False
    assert len(body["file_hash"]) == 64

    res = await client.get(f"/api/v1/parts/revisions/{rid}/files", headers=eng_auth)
    assert res.status_code == 200
    assert [f["id"] for f in res.json()] == [file_id]

    res = await client.get(f"/api/v1/parts/revision-files/{file_id}/download")
    assert res.status_code == 200
    assert res.content == b"hello world"

    res = await client.delete(f"/api/v1/parts/revision-files/{file_id}", headers=eng_auth)
    assert res.status_code == 200

    res = await client.get(f"/api/v1/parts/revisions/{rid}/files", headers=eng_auth)
    assert res.json() == []


async def test_upload_unsupported_extension(client, eng_auth, part):
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files=_upload("malware.exe"),
        headers=eng_auth,
    )
    assert res.status_code == 400


async def test_upload_to_wrong_part_rejected(client, eng_auth, part, seed):
    # Second part without revisions
    res = await client.post(
        "/api/v1/parts",
        json={
            "project_id": seed["project_id"],
            "part_number": "P-200",
            "name": "Other",
            "part_type": "purchased",
            "data_classification": "confidential",
        },
        headers=eng_auth,
    )
    other_part_id = res.json()["id"]

    res = await client.post(
        f"/api/v1/parts/{other_part_id}/revisions/{part['revision_id']}/files",
        files=_upload("doc.txt"),
        headers=eng_auth,
    )
    assert res.status_code == 400


async def test_frozen_revision_rejects_upload_and_delete(
    client, eng_auth, part, session_factory, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    pid, rid = part["part_id"], part["revision_id"]

    res = await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/files", files=_upload("doc.txt"), headers=eng_auth
    )
    file_id = res.json()["id"]

    await freeze_revision(session_factory, rid)

    res = await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/files", files=_upload("more.txt"), headers=eng_auth
    )
    assert res.status_code == 409

    res = await client.delete(f"/api/v1/parts/revision-files/{file_id}", headers=eng_auth)
    assert res.status_code == 409


async def test_changelog_records_file_actions(client, eng_auth, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid, rid = part["part_id"], part["revision_id"]

    await client.post(
        f"/api/v1/parts/{pid}/revisions/{rid}/files", files=_upload("doc.txt"), headers=eng_auth
    )
    res = await client.get(f"/api/v1/parts/{pid}/changelog", headers=eng_auth)
    actions = [e["action"] for e in res.json()]
    assert "file_uploaded" in actions
