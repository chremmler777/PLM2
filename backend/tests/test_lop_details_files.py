"""Project LOP: details text on a line, a clear answer for a title that is too
long, and files attached to a line (upload, list, download, remove)."""
import pytest

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


def _lines(pid):
    return f"{BASE}/projects/{pid}/lines"


def _files(line_id):
    return f"{BASE}/lines/{line_id}/files"


@pytest.fixture
def _uploads_here(monkeypatch, tmp_path):
    """Keep written blobs inside the test's tmp dir."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


async def _history(client, auth, line_id):
    return (await client.get(f"{BASE}/lines/{line_id}/history", headers=auth)).json()


# ---------------------------------------------------------------- details
async def test_a_task_is_created_with_details(client, pm_auth, lop_project):
    r = await client.post(_lines(lop_project.id), headers=pm_auth,
                          json={"title": "Warm measurement", "details": "  Goal: predict\n1. Method  "})
    assert r.status_code == 201, r.text
    assert r.json()["details"] == "Goal: predict\n1. Method"
    assert r.json()["file_count"] == 0


async def test_details_are_optional_and_blank_is_none(client, pm_auth, lop_project):
    b = (await client.post(_lines(lop_project.id), headers=pm_auth,
                           json={"title": "No details", "details": "   "})).json()
    assert b["details"] is None


async def test_pm_changes_details_and_history_says_so(client, pm_auth, line):
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"details": "Step 1"})
    assert r.status_code == 200 and r.json()["details"] == "Step 1"
    ev = [h for h in await _history(client, pm_auth, line) if h.get("field") == "details"]
    assert len(ev) == 1 and ev[0]["new_value"] == "Step 1"
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"details": ""})
    assert r.json()["details"] is None


async def test_the_responsible_cannot_change_details(client, quality_auth, line):
    r = await client.patch(f"{BASE}/lines/{line}", headers=quality_auth, json={"details": "mine"})
    assert r.status_code == 403


async def test_details_have_a_limit(client, pm_auth, lop_project):
    r = await client.post(_lines(lop_project.id), headers=pm_auth,
                          json={"title": "x", "details": "d" * 5001})
    assert r.status_code == 400 and "5000" in r.json()["detail"]


# ------------------------------------------------------------ title limit
async def test_a_title_over_500_characters_is_refused_in_plain_words(client, pm_auth, lop_project):
    r = await client.post(_lines(lop_project.id), headers=pm_auth, json={"title": "t" * 501})
    assert r.status_code == 400
    assert "501" in r.json()["detail"] and "500" in r.json()["detail"] and "Details" in r.json()["detail"]
    ok = await client.post(_lines(lop_project.id), headers=pm_auth, json={"title": "t" * 500})
    assert ok.status_code == 201


async def test_a_long_title_is_refused_on_edit_too(client, pm_auth, line):
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"title": "t" * 501})
    assert r.status_code == 400 and "500" in r.json()["detail"]


# ------------------------------------------------------------------ files
async def test_pm_attaches_files_lists_and_downloads(client, pm_auth, line, lop_project, _uploads_here):
    r = await client.post(_files(line), headers=pm_auth, files=[
        ("files", ("plan.xlsx", b"sheet-bytes", "application/vnd.ms-excel")),
        ("files", ("photo.png", b"\x89PNG fake", "image/png")),
    ])
    assert r.status_code == 201, r.text
    created = r.json()
    assert {f["filename"] for f in created} == {"plan.xlsx", "photo.png"}
    assert all(f["uploaded_by"] == lop_project.pm_id and f["uploaded_by_name"] for f in created)
    assert all(f["can_delete"] for f in created)

    listed = (await client.get(_files(line), headers=pm_auth)).json()
    assert {f["filename"] for f in listed} == {"plan.xlsx", "photo.png"}

    plan = next(f for f in listed if f["filename"] == "plan.xlsx")
    d = await client.get(f"{_files(line)}/{plan['id']}/download", headers=pm_auth)
    assert d.status_code == 200 and d.content == b"sheet-bytes"
    assert "plan.xlsx" in d.headers["content-disposition"]

    got = (await client.get(f"{BASE}/projects/{lop_project.id}", headers=pm_auth)).json()
    assert next(x for x in got["lines"] if x["id"] == line)["file_count"] == 2
    names = [h["new_value"] for h in await _history(client, pm_auth, line) if h.get("field") == "file"]
    assert sorted(names) == ["photo.png", "plan.xlsx"]


async def test_a_team_member_attaches_and_removes_only_their_own(client, pm_auth, quality_auth, line, _uploads_here):
    mine = (await client.post(_files(line), headers=quality_auth,
                              files=[("files", ("evidence.pdf", b"%PDF", "application/pdf"))])).json()[0]
    pms = (await client.post(_files(line), headers=pm_auth,
                             files=[("files", ("pm.txt", b"x", "text/plain"))])).json()[0]
    seen = {f["filename"]: f for f in (await client.get(_files(line), headers=quality_auth)).json()}
    assert seen["evidence.pdf"]["can_delete"] is True and seen["pm.txt"]["can_delete"] is False
    assert (await client.delete(f"{_files(line)}/{pms['id']}", headers=quality_auth)).status_code == 403
    assert (await client.delete(f"{_files(line)}/{mine['id']}", headers=quality_auth)).status_code == 204
    left = (await client.get(_files(line), headers=pm_auth)).json()
    assert [f["filename"] for f in left] == ["pm.txt"]
    # the PM removes anybody's file; a removed file is gone from download too
    assert (await client.delete(f"{_files(line)}/{pms['id']}", headers=pm_auth)).status_code == 204
    assert (await client.get(f"{_files(line)}/{pms['id']}/download", headers=pm_auth)).status_code == 404


async def test_someone_outside_the_team_reads_but_does_not_attach(client, pm_auth, outsider_auth, line, _uploads_here):
    await client.post(_files(line), headers=pm_auth, files=[("files", ("a.txt", b"a", "text/plain"))])
    r = await client.post(_files(line), headers=outsider_auth,
                          files=[("files", ("b.txt", b"b", "text/plain"))])
    assert r.status_code == 403
    listed = await client.get(_files(line), headers=outsider_auth)
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert listed.json()[0]["can_delete"] is False


async def test_a_file_of_another_line_is_not_found(client, pm_auth, line, lop_project, _uploads_here):
    f = (await client.post(_files(line), headers=pm_auth,
                           files=[("files", ("a.txt", b"a", "text/plain"))])).json()[0]
    other = (await client.post(_lines(lop_project.id), headers=pm_auth, json={"title": "Other"})).json()
    assert (await client.get(f"{_files(other['id'])}/{f['id']}/download", headers=pm_auth)).status_code == 404
    assert (await client.delete(f"{_files(other['id'])}/{f['id']}", headers=pm_auth)).status_code == 404


async def test_a_file_that_is_too_large_leaves_nothing(client, pm_auth, line, _uploads_here, monkeypatch):
    from app.services import lop_files
    monkeypatch.setattr(lop_files, "MAX_FILE_SIZE", 4)
    r = await client.post(_files(line), headers=pm_auth, files=[
        ("files", ("ok.txt", b"ok", "text/plain")), ("files", ("big.txt", b"too big", "text/plain"))])
    assert r.status_code == 413 and "big.txt" in r.json()["detail"]
    assert (await client.get(_files(line), headers=pm_auth)).json() == []
    assert not [p for p in (_uploads_here / "uploads").rglob("*") if p.is_file()]
