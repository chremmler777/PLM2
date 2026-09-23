"""Part thumbnail: upload/replace/clear an image, served back byte for byte,
and surfaced as thumbnail_url on the part and in the project payloads."""
import base64

# 1x1 px PNG
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
# Minimal JPEG signature + junk payload (magic bytes are enough for the sniff)
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
NOT_AN_IMAGE = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n"
HTML_NAMED_PNG = b"<html><body>not a png</body></html>"


async def test_upload_png_then_get_returns_same_bytes(client, eng_auth, seed, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid = part["part_id"]

    res = await client.put(
        f"/api/v1/parts/{pid}/thumbnail",
        files={"file": ("part.png", PNG_BYTES, "image/png")},
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
    assert res.json()["thumbnail_url"].startswith(f"/api/v1/parts/{pid}/thumbnail?v=")

    res = await client.get(f"/api/v1/parts/{pid}/thumbnail", headers=eng_auth)
    assert res.status_code == 200
    assert res.content == PNG_BYTES
    assert res.headers["content-type"] == "image/png"
    assert res.headers["cache-control"] == "private, max-age=86400"
    assert res.headers["x-content-type-options"] == "nosniff"


async def test_thumbnail_url_on_get_part(client, eng_auth, seed, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid = part["part_id"]
    res = await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)
    assert res.json()["thumbnail_url"] is None

    await client.put(f"/api/v1/parts/{pid}/thumbnail", files={"file": ("a.png", PNG_BYTES, "image/png")},
                     headers=eng_auth)

    res = await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)
    assert res.json()["thumbnail_url"] is not None
    assert res.json()["thumbnail_url"].startswith(f"/api/v1/parts/{pid}/thumbnail?v=")


async def test_thumbnail_url_in_project_parts_and_structure(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    res = await client.post(
        "/api/v1/parts",
        json={"project_id": seed["project_id"], "part_number": "P-200", "name": "Bracket",
              "part_type": "sub_assembly", "data_classification": "confidential",
              "item_category": "article"},
        headers=eng_auth,
    )
    assert res.status_code in (200, 201), res.text
    pid = res.json()["id"]

    await client.put(f"/api/v1/parts/{pid}/thumbnail", files={"file": ("a.png", PNG_BYTES, "image/png")},
                     headers=eng_auth)

    res = await client.get(f"/api/v1/parts/project/{seed['project_id']}", headers=eng_auth)
    assert res.status_code == 200
    row = next(r for r in res.json() if r["id"] == pid)
    assert row["thumbnail_url"] is not None

    res = await client.get(f"/api/v1/parts/project/{seed['project_id']}/structure", headers=eng_auth)
    assert res.status_code == 200
    article = next(a for a in res.json()["articles"] if a["part_id"] == pid)
    assert article["thumbnail_url"] is not None


async def test_non_image_rejected(client, eng_auth, seed, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid = part["part_id"]

    res = await client.put(f"/api/v1/parts/{pid}/thumbnail", files={"file": ("a.pdf", NOT_AN_IMAGE, "application/pdf")},
                           headers=eng_auth)
    assert res.status_code == 400, res.text

    # HTML disguised as .png with an image content-type: rejected on magic bytes, not filename/content-type
    res = await client.put(f"/api/v1/parts/{pid}/thumbnail",
                           files={"file": ("fake.png", HTML_NAMED_PNG, "image/png")}, headers=eng_auth)
    assert res.status_code == 400, res.text

    res = await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)
    assert res.json()["thumbnail_url"] is None


async def test_oversized_rejected(client, eng_auth, seed, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid = part["part_id"]
    too_big = b"\xff\xd8\xff\xe0" + b"\x00" * (2 * 1024 * 1024 + 1)
    res = await client.put(f"/api/v1/parts/{pid}/thumbnail", files={"file": ("big.jpg", too_big, "image/jpeg")},
                           headers=eng_auth)
    assert res.status_code == 413, res.text


async def test_replace_removes_old_file(client, eng_auth, seed, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid = part["part_id"]

    res = await client.put(f"/api/v1/parts/{pid}/thumbnail", files={"file": ("a.png", PNG_BYTES, "image/png")},
                           headers=eng_auth)
    assert res.status_code == 200

    from app.models.part import Part
    from app.models import get_db
    import app.main as main_mod  # noqa

    import os
    thumb_dir = os.path.join(str(tmp_path), "uploads", "thumbnails", str(pid))
    first_files = set(os.listdir(thumb_dir))
    assert len(first_files) == 1

    res = await client.put(f"/api/v1/parts/{pid}/thumbnail", files={"file": ("b.jpg", JPEG_BYTES, "image/jpeg")},
                           headers=eng_auth)
    assert res.status_code == 200

    second_files = set(os.listdir(thumb_dir))
    assert len(second_files) == 1
    assert second_files != first_files

    res = await client.get(f"/api/v1/parts/{pid}/thumbnail", headers=eng_auth)
    assert res.content == JPEG_BYTES
    assert res.headers["content-type"] == "image/jpeg"


async def test_delete_clears_thumbnail(client, eng_auth, seed, part, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid = part["part_id"]
    await client.put(f"/api/v1/parts/{pid}/thumbnail", files={"file": ("a.png", PNG_BYTES, "image/png")},
                     headers=eng_auth)

    res = await client.delete(f"/api/v1/parts/{pid}/thumbnail", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["thumbnail_url"] is None

    res = await client.get(f"/api/v1/parts/{pid}/thumbnail", headers=eng_auth)
    assert res.status_code == 404

    res = await client.get(f"/api/v1/parts/{pid}", headers=eng_auth)
    assert res.json()["thumbnail_url"] is None


async def test_missing_part_404(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    res = await client.put("/api/v1/parts/999999/thumbnail", files={"file": ("a.png", PNG_BYTES, "image/png")},
                           headers=eng_auth)
    assert res.status_code == 404
    res = await client.get("/api/v1/parts/999999/thumbnail", headers=eng_auth)
    assert res.status_code == 404
    res = await client.delete("/api/v1/parts/999999/thumbnail", headers=eng_auth)
    assert res.status_code == 404
