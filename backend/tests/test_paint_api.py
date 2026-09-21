"""HTTP: paint catalog CRUD and per-part paint setup endpoints."""
import pytest

from app.models.entities import Organization


async def _mk_part(client, auth, seed, number="P-PAINT"):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": "Panel",
        "part_type": "internal_mfg", "data_classification": "confidential"}, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _mk_paint(client, auth, name="RAL 9005 base", **fields):
    body = {"name": name, **fields}
    res = await client.post("/api/v1/paints", json=body, headers=auth)
    assert res.status_code == 201, res.text
    return res.json()


# --- catalog -----------------------------------------------------------

async def test_create_list_get_update_paint(client, eng_auth):
    created = await _mk_paint(client, eng_auth, "RAL 9005 base",
                              paint_type="basecoat", colour_code="RAL 9005",
                              colour_hex="#1a1a1a")
    assert created["id"] and created["is_active"] is True
    assert created["paint_type"] == "basecoat" and created["colour_code"] == "RAL 9005"

    r = await client.get("/api/v1/paints", headers=eng_auth)
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert names == ["RAL 9005 base"]

    r = await client.get(f"/api/v1/paints/{created['id']}", headers=eng_auth)
    assert r.status_code == 200 and r.json()["name"] == "RAL 9005 base"

    r = await client.put(f"/api/v1/paints/{created['id']}", json={"colour_hex": "#202020"},
                         headers=eng_auth)
    assert r.status_code == 200 and r.json()["colour_hex"] == "#202020"
    assert r.json()["name"] == "RAL 9005 base"  # untouched fields kept


async def test_create_paint_duplicate_name_409(client, eng_auth):
    await _mk_paint(client, eng_auth, "Dup name")
    r = await client.post("/api/v1/paints", json={"name": "Dup name"}, headers=eng_auth)
    assert r.status_code == 409, r.text


async def test_update_paint_duplicate_name_409(client, eng_auth):
    await _mk_paint(client, eng_auth, "Paint A")
    b = await _mk_paint(client, eng_auth, "Paint B")
    r = await client.put(f"/api/v1/paints/{b['id']}", json={"name": "Paint A"}, headers=eng_auth)
    assert r.status_code == 409, r.text


async def test_get_and_update_unknown_paint_404(client, eng_auth):
    assert (await client.get("/api/v1/paints/999999", headers=eng_auth)).status_code == 404
    r = await client.put("/api/v1/paints/999999", json={"notes": "x"}, headers=eng_auth)
    assert r.status_code == 404


async def test_invalid_colour_hex_422(client, eng_auth):
    r = await client.post("/api/v1/paints", json={"name": "Bad hex", "colour_hex": "red"},
                          headers=eng_auth)
    assert r.status_code == 422, r.text


async def test_list_active_only_and_query(client, eng_auth):
    keep = await _mk_paint(client, eng_auth, "2K clear", paint_type="clearcoat", colour_code="CLR-1")
    gone = await _mk_paint(client, eng_auth, "Old primer", paint_type="primer")
    await client.put(f"/api/v1/paints/{gone['id']}", json={"is_active": False}, headers=eng_auth)

    r = await client.get("/api/v1/paints", headers=eng_auth)
    assert [p["name"] for p in r.json()] == ["2K clear"]

    r = await client.get("/api/v1/paints", params={"active_only": False}, headers=eng_auth)
    names = [p["name"] for p in r.json()]
    assert "Old primer" in names

    r = await client.get("/api/v1/paints", params={"q": "clear"}, headers=eng_auth)
    assert [p["name"] for p in r.json()] == ["2K clear"]


async def test_used_in(client, eng_auth, seed):
    paint = await _mk_paint(client, eng_auth, "Used paint")
    pid = await _mk_part(client, eng_auth, seed, "P-USEDIN")
    r = await client.put(f"/api/v1/parts/{pid}/paint", headers=eng_auth, json={
        "paint_required": True, "process": "spray", "notes": None,
        "layers": [{"paint_id": paint["id"], "area": "A-side", "notes": None}],
    })
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/paints/{paint['id']}/used-in", headers=eng_auth)
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) == 1
    assert entries[0]["part_id"] == pid and entries[0]["layer_order"] == 1
    assert entries[0]["project_code"] == "proj"


async def test_used_in_unknown_paint_404(client, eng_auth):
    r = await client.get("/api/v1/paints/999999/used-in", headers=eng_auth)
    assert r.status_code == 404


# --- part paint setup ----------------------------------------------------

async def test_get_part_paint_empty(client, eng_auth, seed):
    pid = await _mk_part(client, eng_auth, seed, "P-EMPTY")
    r = await client.get(f"/api/v1/parts/{pid}/paint", headers=eng_auth)
    assert r.status_code == 200
    assert r.json() == {"paint_required": False, "process": None, "notes": None, "layers": []}


async def test_put_get_part_paint_round_trip(client, eng_auth, seed):
    base = await _mk_paint(client, eng_auth, "RAL 9005 base", paint_type="basecoat")
    clear = await _mk_paint(client, eng_auth, "2K clear", paint_type="clearcoat")
    pid = await _mk_part(client, eng_auth, seed, "P-ROUND")

    r = await client.put(f"/api/v1/parts/{pid}/paint", headers=eng_auth, json={
        "paint_required": True, "process": "spray", "notes": "outer only",
        "layers": [
            {"paint_id": base["id"], "area": "A-side", "notes": "2 passes"},
            {"paint_id": clear["id"]},
        ],
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["paint_required"] is True and out["process"] == "spray"
    assert [ly["layer_order"] for ly in out["layers"]] == [1, 2]
    assert [ly["paint"]["name"] for ly in out["layers"]] == ["RAL 9005 base", "2K clear"]
    assert out["layers"][0]["area"] == "A-side"

    r = await client.get(f"/api/v1/parts/{pid}/paint", headers=eng_auth)
    assert r.status_code == 200 and r.json() == out


async def test_put_part_paint_unknown_part_404(client, eng_auth):
    r = await client.put("/api/v1/parts/999999/paint", headers=eng_auth, json={
        "paint_required": False, "layers": []})
    assert r.status_code == 404


async def test_get_part_paint_unknown_part_404(client, eng_auth):
    r = await client.get("/api/v1/parts/999999/paint", headers=eng_auth)
    assert r.status_code == 404


async def test_put_part_paint_foreign_paint_400(client, eng_auth, seed, session_factory):
    pid = await _mk_part(client, eng_auth, seed, "P-FOREIGN")

    async with session_factory() as s:
        from app.services.paint_service import PaintService
        other = Organization(name="Other Org", code="other-org-api", is_active=True)
        s.add(other)
        await s.flush()
        foreign = await PaintService.create_paint(
            s, org_id=other.id, created_by=seed["admin_id"], name="Foreign paint")
        await s.commit()
        foreign_id = foreign.id

    r = await client.put(f"/api/v1/parts/{pid}/paint", headers=eng_auth, json={
        "paint_required": True, "layers": [{"paint_id": foreign_id}]})
    assert r.status_code == 400, r.text


async def test_part_paint_cross_org_part_is_404(client, eng_auth, seed, session_factory):
    """A part id from another org's project must 404, not leak the setup."""
    pid = await _mk_part(client, eng_auth, seed, "P-XORG")

    async with session_factory() as s:
        from app.models.entities import Organization, Plant, Project
        from app.models.part import Part
        other = Organization(name="Other Org 2", code="other-org-2", is_active=True)
        s.add(other)
        await s.flush()
        plant = Plant(organization_id=other.id, name="Other Plant", code="op", location="DE",
                      is_active=True)
        s.add(plant)
        await s.flush()
        project = Project(plant_id=plant.id, name="Other Project", code="oproj", status="active")
        s.add(project)
        await s.flush()
        foreign_part = Part(project_id=project.id, part_number="F-1", name="Foreign",
                            part_type="internal_mfg", created_by=seed["admin_id"])
        s.add(foreign_part)
        await s.commit()
        foreign_part_id = foreign_part.id

    r = await client.get(f"/api/v1/parts/{foreign_part_id}/paint", headers=eng_auth)
    assert r.status_code == 404


# --- project overview ------------------------------------------------------

async def test_paint_overview_after_put(client, eng_auth, seed):
    paint = await _mk_paint(client, eng_auth, "Overview paint")
    pid = await _mk_part(client, eng_auth, seed, "P-OVERVIEW")
    not_painted = await _mk_part(client, eng_auth, seed, "P-NOPAINT")

    r = await client.put(f"/api/v1/parts/{pid}/paint", headers=eng_auth, json={
        "paint_required": True, "process": "spray",
        "layers": [{"paint_id": paint["id"], "area": None, "notes": None}]})
    assert r.status_code == 200

    r = await client.get(f"/api/v1/parts/project/{seed['project_id']}/paint-overview",
                         headers=eng_auth)
    assert r.status_code == 200
    parts = r.json()
    assert [p["part_id"] for p in parts] == [pid]
    assert parts[0]["process"] == "spray"
    assert parts[0]["layers"][0]["paint"]["name"] == "Overview paint"
    assert not_painted not in [p["part_id"] for p in parts]


async def test_paint_overview_unknown_project_404(client, eng_auth):
    r = await client.get("/api/v1/parts/project/999999/paint-overview", headers=eng_auth)
    assert r.status_code == 404
