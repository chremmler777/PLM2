"""Files on SEP work items: upload, list, download, soft delete, project
overview, the file_count on the SEP payload, and the org boundary."""
import hashlib

import pytest
from sqlalchemy import select

from app.models.entities import Organization, Plant, Project
from app.models.sep import SepGate, SepItemAudit, SepItemFile, SepWorkItem
from app.services import sep_file_service


async def _activate(client, auth, project_id):
    res = await client.post(f"/api/v1/sep/projects/{project_id}/activate", headers=auth)
    assert res.status_code == 201, res.text
    return res.json()


async def _get_sep(client, auth, project_id):
    res = await client.get(f"/api/v1/sep/projects/{project_id}", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _first_item(client, auth, project_id):
    """Activate SEP and return (gate, first work item of gate 1)."""
    await _activate(client, auth, project_id)
    full = await _get_sep(client, auth, project_id)
    gate = full["gates"][0]
    return gate, gate["items"][0]


async def _upload(client, auth, item_id, files):
    return await client.post(f"/api/v1/sep/items/{item_id}/files", files=files, headers=auth)


@pytest.fixture
def _uploads_here(monkeypatch, tmp_path):
    """Keep written blobs inside the test's tmp dir."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


async def test_upload_two_files_and_list(client, eng_auth, seed, _uploads_here):
    _, item = await _first_item(client, eng_auth, seed["project_id"])

    res = await _upload(client, eng_auth, item["id"], [
        ("files", ("plan.xlsx", b"sheet-bytes",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ("files", ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")),
    ])
    assert res.status_code == 201, res.text
    created = res.json()
    assert {f["filename"] for f in created} == {"plan.xlsx", "scan.pdf"}
    by_name = {f["filename"]: f for f in created}
    assert by_name["plan.xlsx"]["sha256"] == hashlib.sha256(b"sheet-bytes").hexdigest()
    assert by_name["plan.xlsx"]["size_bytes"] == len(b"sheet-bytes")
    assert by_name["scan.pdf"]["content_type"] == "application/pdf"
    assert all(f["item_id"] == item["id"] for f in created)
    assert all(f["uploaded_by"] == seed["engineer_id"] for f in created)
    assert all(f["uploaded_by_name"] == "Engineer" for f in created)

    res = await client.get(f"/api/v1/sep/items/{item['id']}/files", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert {f["filename"] for f in res.json()} == {"plan.xlsx", "scan.pdf"}


async def test_download_returns_the_original_bytes(client, eng_auth, seed, _uploads_here):
    _, item = await _first_item(client, eng_auth, seed["project_id"])
    created = (await _upload(client, eng_auth, item["id"], [
        ("files", ("report.docx", b"docx-bytes", "application/octet-stream"))])).json()

    res = await client.get(
        f"/api/v1/sep/items/{item['id']}/files/{created[0]['id']}/download", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.content == b"docx-bytes"
    assert "report.docx" in res.headers["content-disposition"]


async def test_download_404_for_a_file_on_another_item(client, eng_auth, seed, _uploads_here):
    full_gate, item = await _first_item(client, eng_auth, seed["project_id"])
    other_item = full_gate["items"][1]
    created = (await _upload(client, eng_auth, item["id"], [
        ("files", ("a.txt", b"a", "text/plain"))])).json()

    res = await client.get(
        f"/api/v1/sep/items/{other_item['id']}/files/{created[0]['id']}/download", headers=eng_auth)
    assert res.status_code == 404


async def test_soft_delete_hides_the_file_but_keeps_the_row(
        client, eng_auth, seed, session_factory, _uploads_here):
    _, item = await _first_item(client, eng_auth, seed["project_id"])
    created = (await _upload(client, eng_auth, item["id"], [
        ("files", ("keep.txt", b"keep", "text/plain")),
        ("files", ("gone.txt", b"gone", "text/plain")),
    ])).json()
    doomed = next(f for f in created if f["filename"] == "gone.txt")

    res = await client.delete(
        f"/api/v1/sep/items/{item['id']}/files/{doomed['id']}", headers=eng_auth)
    assert res.status_code == 204, res.text

    listed = (await client.get(f"/api/v1/sep/items/{item['id']}/files", headers=eng_auth)).json()
    assert [f["filename"] for f in listed] == ["keep.txt"]

    res = await client.get(
        f"/api/v1/sep/items/{item['id']}/files/{doomed['id']}/download", headers=eng_auth)
    assert res.status_code == 404

    async with session_factory() as s:
        row = (await s.execute(
            select(SepItemFile).where(SepItemFile.id == doomed["id"]))).scalar_one()
        assert row.is_deleted is True
        assert row.deleted_at is not None
        assert row.deleted_by == seed["engineer_id"]


async def test_project_files_grouped_by_gate_and_item(client, eng_auth, seed, _uploads_here):
    gate, item = await _first_item(client, eng_auth, seed["project_id"])
    full = await _get_sep(client, eng_auth, seed["project_id"])
    second_gate = full["gates"][1]
    second_item = second_gate["items"][0]
    empty_item = gate["items"][1]

    await _upload(client, eng_auth, item["id"], [("files", ("one.txt", b"1", "text/plain"))])
    await _upload(client, eng_auth, second_item["id"],
                  [("files", ("two.txt", b"22", "text/plain"))])

    res = await client.get(
        f"/api/v1/sep/projects/{seed['project_id']}/files", headers=eng_auth)
    assert res.status_code == 200, res.text
    groups = res.json()
    assert [g["gate_code"] for g in groups] == [gate["code"], second_gate["code"]]
    assert [g["seq"] for g in groups] == [1, 2]
    assert groups[0]["phase_en"] == gate["phase_en"]
    assert [i["item_id"] for i in groups[0]["items"]] == [item["id"]]
    assert empty_item["id"] not in {i["item_id"] for g in groups for i in g["items"]}
    assert groups[0]["items"][0]["title_en"] == item["title_en"]
    assert groups[0]["items"][0]["department"] == item["department"]
    assert [f["filename"] for f in groups[0]["items"][0]["files"]] == ["one.txt"]
    assert [f["filename"] for f in groups[1]["items"][0]["files"]] == ["two.txt"]


async def test_file_count_on_the_project_payload(client, eng_auth, seed, _uploads_here):
    gate, item = await _first_item(client, eng_auth, seed["project_id"])
    await _upload(client, eng_auth, item["id"], [
        ("files", ("a.txt", b"a", "text/plain")),
        ("files", ("b.txt", b"b", "text/plain")),
    ])

    full = await _get_sep(client, eng_auth, seed["project_id"])
    first_gate = full["gates"][0]
    assert first_gate["file_count"] == 2
    counted = {i["id"]: i["file_count"] for i in first_gate["items"]}
    assert counted[item["id"]] == 2
    assert counted[gate["items"][1]["id"]] == 0
    assert full["gates"][1]["file_count"] == 0

    # a soft delete brings the count back down
    files = (await client.get(f"/api/v1/sep/items/{item['id']}/files", headers=eng_auth)).json()
    await client.delete(f"/api/v1/sep/items/{item['id']}/files/{files[0]['id']}", headers=eng_auth)
    full = await _get_sep(client, eng_auth, seed["project_id"])
    assert full["gates"][0]["file_count"] == 1


async def test_upload_rejects_a_file_over_the_cap(
        client, eng_auth, seed, monkeypatch, _uploads_here):
    _, item = await _first_item(client, eng_auth, seed["project_id"])
    monkeypatch.setattr(sep_file_service, "MAX_FILE_SIZE", 4)

    res = await _upload(client, eng_auth, item["id"], [
        ("files", ("huge.bin", b"0123456789", "application/octet-stream"))])
    assert res.status_code == 413, res.text
    assert res.json()["detail"] == "File huge.bin exceeds 100MB"

    listed = (await client.get(f"/api/v1/sep/items/{item['id']}/files", headers=eng_auth)).json()
    assert listed == []


async def test_upload_rejects_an_empty_filename(client, eng_auth, seed, _uploads_here):
    _, item = await _first_item(client, eng_auth, seed["project_id"])
    res = await _upload(client, eng_auth, item["id"], [
        ("files", ("", b"bytes", "application/octet-stream"))])
    assert res.status_code == 422, res.text


async def test_item_of_another_org_is_a_404(
        client, eng_auth, seed, session_factory, _uploads_here):
    async with session_factory() as s:
        org = Organization(name="Other Org", code="other-org", is_active=True)
        s.add(org)
        await s.flush()
        plant = Plant(organization_id=org.id, name="Other Plant", code="other-plant",
                      location="DE", is_active=True)
        s.add(plant)
        await s.flush()
        project = Project(plant_id=plant.id, name="Other Project", code="other-proj",
                          status="active")
        s.add(project)
        await s.flush()
        gate = SepGate(project_id=project.id, code="K0/RG1", seq=1,
                       phase_de="Phase", phase_en="Phase", status="in_progress")
        s.add(gate)
        await s.flush()
        foreign_item = SepWorkItem(gate_id=gate.id, project_id=project.id, item_no=1,
                                   title_de="t", title_en="t", department="PM")
        s.add(foreign_item)
        await s.commit()
        foreign_item_id, foreign_project_id = foreign_item.id, project.id

    res = await _upload(client, eng_auth, foreign_item_id, [
        ("files", ("x.txt", b"x", "text/plain"))])
    assert res.status_code == 404
    res = await client.get(f"/api/v1/sep/items/{foreign_item_id}/files", headers=eng_auth)
    assert res.status_code == 404
    res = await client.delete(f"/api/v1/sep/items/{foreign_item_id}/files/1", headers=eng_auth)
    assert res.status_code == 404
    res = await client.get(f"/api/v1/sep/projects/{foreign_project_id}/files", headers=eng_auth)
    assert res.status_code == 404


async def test_uploads_and_deletes_are_audited(
        client, eng_auth, seed, session_factory, _uploads_here):
    _, item = await _first_item(client, eng_auth, seed["project_id"])
    created = (await _upload(client, eng_auth, item["id"], [
        ("files", ("audit-me.txt", b"x", "text/plain"))])).json()
    await client.delete(
        f"/api/v1/sep/items/{item['id']}/files/{created[0]['id']}", headers=eng_auth)

    async with session_factory() as s:
        audits = list((await s.execute(
            select(SepItemAudit)
            .where(SepItemAudit.item_id == item["id"], SepItemAudit.field == "file")
            .order_by(SepItemAudit.id)
        )).scalars())
    assert len(audits) == 2
    assert audits[0].new_value == "audit-me.txt" and audits[0].old_value is None
    assert audits[1].old_value == "audit-me.txt" and audits[1].new_value is None
    assert all(a.user_id == seed["engineer_id"] for a in audits)
