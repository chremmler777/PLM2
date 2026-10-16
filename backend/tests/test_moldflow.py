"""Moldflow timing rows: project overview with articles, CRUD with audit,
the tool-data write rule (Tool Engineer or admin), uniqueness per tool +
version + layout, soft delete, derived status, and the worksheet cell."""
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.models.entities import AuditLog
from app.models.moldflow import ToolMoldflow
from app.models.part import Part, PartRelation
from app.services.moldflow_service import derive_status, latest, worksheet_cell
from tests.test_dfm_project_scope import _dept


@pytest.fixture(autouse=True)
def _tool_engineer_member(tool_engineer):
    """Moldflow writes follow the tool data rule; the seeded engineer works as Tool Engineer."""


async def _tools(session_factory, seed):
    uid = seed["engineer_id"]
    async with session_factory() as s:
        def part(number, category="article", **kw):
            kw.setdefault("name", f"Name {number}")
            p = Part(project_id=seed["project_id"], part_number=number,
                     part_type="internal_mfg", item_category=category, created_by=uid, **kw)
            s.add(p)
            return p
        lh = part("20-1994-001-0", customer_part_number="206.882.251", tier1_part_number="S00H4X-110",
                  name="Handle height adj LH")
        rh = part("20-1994-002-0", customer_part_number="206.882.252", tier1_part_number="S00H4W-110",
                  name="Handle height adj RH")
        tool = part("199401", "tool", tool_cavities="2+2")
        spare = part("199413", "tool")
        await s.flush()
        s.add_all([PartRelation(from_part_id=tool.id, to_part_id=lh.id, relation_type="produces", created_by=uid),
                   PartRelation(from_part_id=tool.id, to_part_id=rh.id, relation_type="produces", created_by=uid)])
        await s.commit()
        return {"lh": lh.id, "rh": rh.id, "tool": tool.id, "spare": spare.id}


async def test_crud_overview_and_audit(client, eng_auth, seed, session_factory):
    ids = await _tools(session_factory, seed)
    res = await client.post(f"/api/v1/parts/{ids['tool']}/moldflow", json={
        "geometry_status": "ready", "gate_status": "ready", "udb_status": "n/a",
        "material_label": " PA6-GF15 ", "source_ref": "mail"}, headers=eng_auth)
    assert res.status_code == 201, res.text
    row = res.json()
    assert (row["version"], row["cavity_layout"], row["status"]) == ("V1", None, "ready_for_mf")
    assert row["material_label"] == "PA6-GF15" and row["created_by"] == seed["engineer_id"]

    res = await client.patch(f"/api/v1/moldflow/{row['id']}", json={
        "received_on": "2026-10-15", "status": "received", "blockers": "clamp force high"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["received_on"] == "2026-10-15" and res.json()["derived_status"] == "received"

    v2 = await client.post(f"/api/v1/parts/{ids['tool']}/moldflow", json={"version": "2"}, headers=eng_auth)
    assert v2.status_code == 201 and v2.json()["version"] == "V2" and v2.json()["status"] == "not_started"

    data = (await client.get(f"/api/v1/projects/{seed['project_id']}/moldflow", headers=eng_auth)).json()
    assert data["can_edit"] is True
    tools = {t["tool"]["part_number"]: t for t in data["tools"]}
    assert set(tools) == {"199401", "199413"} and tools["199413"]["rows"] == []
    t = tools["199401"]
    assert t["tool"]["cavities"] == "2+2"
    assert [(a["customer_part_number"], a["tier1_part_number"]) for a in t["articles"]] == [
        ("206.882.251", "S00H4X-110"), ("206.882.252", "S00H4W-110")]
    assert [r["version"] for r in t["rows"]] == ["V1", "V2"] and t["latest_id"] == v2.json()["id"]

    assert (await client.delete(f"/api/v1/moldflow/{v2.json()['id']}", headers=eng_auth)).status_code == 204
    assert (await client.patch(f"/api/v1/moldflow/{v2.json()['id']}", json={"notes": "x"},
                               headers=eng_auth)).status_code == 404
    data = (await client.get(f"/api/v1/projects/{seed['project_id']}/moldflow", headers=eng_auth)).json()
    assert [r["version"] for r in data["tools"][0]["rows"]] == ["V1"]
    # a deleted version can be added again
    assert (await client.post(f"/api/v1/parts/{ids['tool']}/moldflow", json={"version": "V2"},
                              headers=eng_auth)).status_code == 201

    async with session_factory() as s:
        actions = [a.action for a in (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "tool_moldflow").order_by(AuditLog.id))).scalars()]
        assert actions == ["moldflow_created", "moldflow_updated", "moldflow_created", "moldflow_deleted",
                           "moldflow_created"]
        upd = (await s.execute(select(AuditLog).where(AuditLog.action == "moldflow_updated"))).scalar_one()
        assert '"received_on": null' in upd.old_values and '"2026-10-15"' in upd.new_values


async def test_unique_per_version_and_layout(client, eng_auth, seed, session_factory):
    ids = await _tools(session_factory, seed)
    url = f"/api/v1/parts/{ids['tool']}/moldflow"
    assert (await client.post(url, json={}, headers=eng_auth)).status_code == 201
    dup = await client.post(url, json={"version": "v1"}, headers=eng_auth)
    assert dup.status_code == 409
    two = await client.post(url, json={"cavity_layout": "2"}, headers=eng_auth)
    four = await client.post(url, json={"cavity_layout": "2+2"}, headers=eng_auth)
    assert two.status_code == 201 and four.status_code == 201
    res = await client.patch(f"/api/v1/moldflow/{four.json()['id']}", json={"cavity_layout": "2"}, headers=eng_auth)
    assert res.status_code == 409


async def test_validation(client, eng_auth, seed, session_factory):
    ids = await _tools(session_factory, seed)
    url = f"/api/v1/parts/{ids['tool']}/moldflow"
    assert (await client.post(url, json={"status": "bogus"}, headers=eng_auth)).status_code == 422
    assert (await client.post(url, json={"gate_status": "done"}, headers=eng_auth)).status_code == 422
    assert (await client.post(url, json={"version": "Version A"}, headers=eng_auth)).status_code == 422
    assert (await client.post(url, json={"tool_part_id": 1}, headers=eng_auth)).status_code == 422
    art = await client.post(f"/api/v1/parts/{ids['lh']}/moldflow", json={}, headers=eng_auth)
    assert art.status_code == 400 and art.json()["detail"] == "Moldflow rows belong to tools"
    row = (await client.post(url, json={}, headers=eng_auth)).json()
    res = await client.patch(f"/api/v1/moldflow/{row['id']}", json={"status": None}, headers=eng_auth)
    assert res.status_code == 400


async def test_view_only_outside_tool_engineer(client, eng_auth, admin_auth, seed, session_factory):
    from app.services.tool_rights import TOOL_EDIT_DENIED
    ids = await _tools(session_factory, seed)
    quality = await _dept(session_factory, "Quality")
    as_quality = {**admin_auth, "X-Acts-As-Department": str(quality)}
    row = (await client.post(f"/api/v1/parts/{ids['tool']}/moldflow", json={}, headers=eng_auth)).json()
    res = await client.get(f"/api/v1/projects/{seed['project_id']}/moldflow", headers=as_quality)
    assert res.status_code == 200 and res.json()["can_edit"] is False
    res = await client.post(f"/api/v1/parts/{ids['tool']}/moldflow", json={"version": "V2"}, headers=as_quality)
    assert res.status_code == 403 and res.json()["detail"] == TOOL_EDIT_DENIED
    assert (await client.patch(f"/api/v1/moldflow/{row['id']}", json={"notes": "n"},
                               headers=as_quality)).status_code == 403
    assert (await client.delete(f"/api/v1/moldflow/{row['id']}", headers=as_quality)).status_code == 403
    assert (await client.patch(f"/api/v1/moldflow/{row['id']}", json={"notes": "n"},
                               headers=admin_auth)).status_code == 200


async def test_worksheet_carries_latest_moldflow(client, eng_auth, seed, session_factory):
    ids = await _tools(session_factory, seed)
    async with session_factory() as s:
        s.add_all([
            ToolMoldflow(tool_part_id=ids["tool"], version="V1", status="sent_to_customer",
                         received_on=date(2026, 10, 15), sent_customer_on=date(2026, 10, 15),
                         updated_at=datetime(2026, 10, 15)),
            ToolMoldflow(tool_part_id=ids["tool"], version="V2", cavity_layout="2", status="running",
                         mf_requested_on=date(2026, 10, 16), updated_at=datetime(2026, 10, 16)),
            ToolMoldflow(tool_part_id=ids["tool"], version="V2", cavity_layout="2+2", status="inputs_open",
                         blockers="UDB", updated_at=datetime(2026, 10, 17)),
            ToolMoldflow(tool_part_id=ids["tool"], version="V3", status="final",
                         deleted_at=datetime(2026, 10, 17)),
        ])
        await s.commit()
    rows = {r["part_id"]: r for r in (await client.get(
        f"/api/v1/projects/{seed['project_id']}/worksheet", headers=eng_auth)).json()["rows"]}
    cell = rows[ids["lh"]]["moldflow"]
    assert (cell["version"], cell["cavity_layout"], cell["status"], cell["blockers"]) == ("V2", "2+2", "inputs_open", "UDB")
    assert (cell["layouts"], cell["versions"], cell["last_step"]) == (2, 2, None)
    assert rows[ids["rh"]]["moldflow"] == cell
    assert rows[ids["spare"]]["moldflow"] is None


def test_derive_status_and_latest():
    r = ToolMoldflow(geometry_status="open", gate_status="open", udb_status="open")
    assert derive_status(r) == "not_started"
    r.material_label = "Romiloy 3020/11"
    assert derive_status(r) == "inputs_open"
    r.geometry_status, r.gate_status, r.udb_status = "ready", "ready", "n/a"
    assert derive_status(r) == "ready_for_mf"
    for col, expected in (("mf_requested_on", "running"), ("received_on", "received"),
                          ("ktx_review_on", "in_review"), ("sent_customer_on", "sent_to_customer"),
                          ("customer_feedback_on", "customer_feedback"), ("final_on", "final")):
        setattr(r, col, date(2026, 10, 15))
        assert derive_status(r) == expected
    assert latest([]) is None and worksheet_cell([]) is None
    v9 = ToolMoldflow(id=1, version="V9", updated_at=datetime(2026, 1, 1))
    v10 = ToolMoldflow(id=2, version="V10", updated_at=datetime(2025, 1, 1))
    assert latest([v9, v10]) is v10
    v10.sent_customer_on = date(2026, 10, 15)
    assert worksheet_cell([v9, v10])["last_step"] == {"key": "sent_customer_on", "label": "Sent to customer",
                                                      "on": "2026-10-15"}
