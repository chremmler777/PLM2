async def test_upload_stores_kind_and_note(client, eng_auth, part):
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("206_881_479____PCA_TM__003_____X.CATPart", b"catia-bytes", "application/octet-stream")},
        data={"kind": "PCA", "note": "PCA engineering master."}, headers=eng_auth)
    assert up.status_code in (200, 201), up.text
    assert up.json()["kind"] == "PCA"
    assert up.json()["note"] == "PCA engineering master."
    rows = (await client.get(f"/api/v1/parts/revisions/{part['revision_id']}/files", headers=eng_auth)).json()
    assert rows[0]["kind"] == "PCA"
    assert rows[0]["note"] == "PCA engineering master."


async def test_upload_without_kind_and_note_is_unchanged(client, eng_auth, part):
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("drawing.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"file_type": "drawing"}, headers=eng_auth)
    assert up.status_code in (200, 201), up.text
    assert up.json()["kind"] is None and up.json()["note"] is None
    assert up.json()["file_type"] == "drawing"


async def test_note_on_a_drawing_is_kept_without_cad_data(client, eng_auth, part):
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("d.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"file_type": "drawing", "kind": "DRW", "note": "DRW customer part drawing."}, headers=eng_auth)
    assert up.status_code in (200, 201), up.text
    assert up.json()["kind"] == "DRW"
    assert up.json()["note"] == "DRW customer part drawing."


async def test_note_too_long_is_rejected(client, eng_auth, part):
    up = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/files",
        files={"file": ("d.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"note": "x" * 501}, headers=eng_auth)
    assert up.status_code == 422
