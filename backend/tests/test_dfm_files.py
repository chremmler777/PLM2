"""DFM files: download the stored bytes, PDFs inline for the document pane,
and a storage failure records nothing."""
import os

from tests.test_dfm_entries import make_topic, post_entry
from tests.test_dfm_topics import make_tool


async def _entry_with(client, eng_auth, seed, files):
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    res = await post_entry(client, eng_auth, tool, topic, files=files)
    assert res.status_code == 201, res.text
    return tool, topic, res.json()


async def test_download_returns_stored_bytes(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool, _, entry = await _entry_with(client, eng_auth, seed, [("ISOFIX_DFM_r1.pdf", b"%PDF-1.4 r1", "application/pdf")])
    fid = entry["files"][0]["id"]
    res = await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/download", headers=eng_auth)
    assert res.status_code == 200
    assert res.content == b"%PDF-1.4 r1"
    assert res.headers["content-disposition"].startswith("attachment")
    assert "ISOFIX_DFM_r1.pdf" in res.headers["content-disposition"]


async def test_inline_pdf_only(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool, _, entry = await _entry_with(client, eng_auth, seed, [
        ("study.pdf", b"%PDF-1.4 s", "application/pdf"),
        ("mail.msg", b"mail", "application/vnd.ms-outlook"),
    ])
    pdf_id, msg_id = entry["files"][0]["id"], entry["files"][1]["id"]
    res = await client.get(f"/api/v1/parts/{tool}/dfm/files/{pdf_id}/inline", headers=eng_auth)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.headers["content-disposition"].startswith("inline")
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/{msg_id}/inline", headers=eng_auth)).status_code == 415


async def test_file_must_belong_to_the_tool(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool, _, entry = await _entry_with(client, eng_auth, seed, [("a.pdf", b"%PDF a", "application/pdf")])
    other = await make_tool(client, eng_auth, seed, number="199404")
    fid = entry["files"][0]["id"]
    assert (await client.get(f"/api/v1/parts/{other}/dfm/files/{fid}/download", headers=eng_auth)).status_code == 404
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/999999/download", headers=eng_auth)).status_code == 404


async def test_missing_on_disk_is_404(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool, _, entry = await _entry_with(client, eng_auth, seed, [("a.pdf", b"%PDF a", "application/pdf")])
    folder = tmp_path / "uploads" / "dfm" / str(tool) / str(entry["id"])
    for name in os.listdir(folder):
        os.remove(folder / name)
    fid = entry["files"][0]["id"]
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/download", headers=eng_auth)).status_code == 404


async def test_storage_failure_records_nothing(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)

    import app.services.dfm_service as svc

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(svc.os, "makedirs", boom)

    res = await post_entry(client, eng_auth, tool, topic, files=[("a.pdf", b"%PDF a", "application/pdf")])
    assert res.status_code == 500
    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic}", headers=eng_auth)
    assert res.json()["entries"] == []
    assert res.json()["entry_count"] == 0
    assert not (tmp_path / "uploads" / "dfm").exists()
