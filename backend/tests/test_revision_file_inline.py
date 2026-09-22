async def _upload(client, auth, part, name, payload, ctype, file_type=None):
    data = {"file_type": file_type} if file_type else {}
    r = await client.post(f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
                          files={"file": (name, payload, ctype)}, data=data, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_inline_pdf_is_served_inline(client, eng_auth, part):
    fid = await _upload(client, eng_auth, part, "drawing.pdf", b"%PDF-1.4 x", "application/pdf", "drawing")
    r = await client.get(f"/api/v1/parts/revision-files/{fid}/inline")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"].startswith("inline")
    assert r.content == b"%PDF-1.4 x"


async def test_inline_picture(client, eng_auth, part):
    fid = await _upload(client, eng_auth, part, "photo.png", b"\x89PNG", "image/png")
    r = await client.get(f"/api/v1/parts/revision-files/{fid}/inline")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")


async def test_inline_non_latin1_filename_uses_rfc5987_encoding(client, eng_auth, part):
    fid = await _upload(client, eng_auth, part, "Prüfung—A.pdf", b"%PDF-1.4 z", "application/pdf", "drawing")
    r = await client.get(f"/api/v1/parts/revision-files/{fid}/inline")
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("inline")
    assert "filename*=utf-8''" in disposition


async def test_inline_refuses_other_types(client, eng_auth, part):
    fid = await _upload(client, eng_auth, part, "model.stp", b"ISO-10303-21;", "application/step")
    r = await client.get(f"/api/v1/parts/revision-files/{fid}/inline")
    assert r.status_code == 415


async def test_inline_unknown_and_deleted(client, eng_auth, part):
    assert (await client.get("/api/v1/parts/revision-files/999999/inline")).status_code == 404
    fid = await _upload(client, eng_auth, part, "d.pdf", b"%PDF-1.4 y", "application/pdf", "drawing")
    assert (await client.delete(f"/api/v1/parts/revision-files/{fid}", headers=eng_auth)).status_code == 200
    assert (await client.get(f"/api/v1/parts/revision-files/{fid}/inline")).status_code == 404
