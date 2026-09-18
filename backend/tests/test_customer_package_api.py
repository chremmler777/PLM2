"""HTTP flow of the customer package receive."""
import json

from app.models.part import Part


async def _mk_part(client, auth, seed, number, customer_number=None, part_type="internal_mfg", session_factory=None):
    body = {"project_id": seed["project_id"], "part_number": number, "name": number,
            "part_type": part_type, "data_classification": "confidential"}
    res = await client.post("/api/v1/parts", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    pid = res.json()["id"]
    if customer_number:
        assert session_factory is not None
        async with session_factory() as s:
            part = await s.get(Part, pid)
            part.customer_part_number = customer_number
            await s.commit()
    r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=auth,
                          json={"statement": "review", "received_at": "2026-09-01", "customer_index": "A"})
    assert r.status_code == 201, r.text
    return pid, r.json()["id"]


async def test_preview_then_confirm(client, eng_auth, seed, tmp_path, monkeypatch, session_factory):
    monkeypatch.chdir(tmp_path)
    top, top_rev = await _mk_part(client, eng_auth, seed, "1994-100", "3CR.807.425", session_factory=session_factory)
    sub, _ = await _mk_part(client, eng_auth, seed, "1994-110", "3CR.807.531", session_factory=session_factory)
    r = await client.post(f"/api/v1/parts/{top}/revisions/{top_rev}/bom", headers=eng_auth,
                          json={"child_part_id": sub, "quantity": 1, "unit": "pcs"})
    assert r.status_code in (200, 201), r.text

    files = [("files", ("3CR807425B_top.stp", b"ISO-10303-21;", "model/step")),
             ("files", ("3CR807531A_sub.stp", b"ISO-10303-21;", "model/step"))]
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-package/preview", headers=eng_auth,
                          data={"statement": "review", "received_at": "2026-09-10", "package_index": "B"}, files=files)
    assert r.status_code == 200, r.text
    rows = {x["filename"]: x for x in r.json()["rows"]}
    assert rows["3CR807425B_top.stp"]["action"] == "new_major" and rows["3CR807425B_top.stp"]["suggested_name"] == "E2"
    assert rows["3CR807531A_sub.stp"]["action"] == "unchanged"

    confirm_rows = [{"filename": "3CR807425B_top.stp", "part_id": top, "customer_index": "B", "action": "new_major", "major": None},
                    {"filename": "3CR807531A_sub.stp", "part_id": sub, "customer_index": "A", "action": "unchanged", "major": None}]
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-package", headers=eng_auth,
                          data={"statement": "review", "received_at": "2026-09-10", "rows": json.dumps(confirm_rows)}, files=files)
    assert r.status_code == 201, r.text
    out = r.json()
    assert [c["revision_name"] for c in out["created"]] == ["E2"] and len(out["kept"]) == 1

    part = (await client.get(f"/api/v1/parts/{top}", headers=eng_auth)).json()
    assert [x["revision_name"] for x in part["revisions"]] == ["E1", "E2"]


async def test_confirm_reports_row_errors(client, eng_auth, seed, tmp_path, monkeypatch, session_factory):
    monkeypatch.chdir(tmp_path)
    top, _ = await _mk_part(client, eng_auth, seed, "1994-200", "3CR.807.999", session_factory=session_factory)
    rows = [{"filename": "top.stp", "part_id": top, "customer_index": "B", "action": "new_major", "major": 1}]
    r = await client.post(f"/api/v1/parts/{top}/revisions/customer-package", headers=eng_auth,
                          data={"statement": "review", "received_at": "2026-09-10", "rows": json.dumps(rows)},
                          files=[("files", ("top.stp", b"x", "model/step"))])
    assert r.status_code == 409, r.text
    assert r.json()["rows"][0]["action"] == "error" and "above E1" in r.json()["rows"][0]["error"]
