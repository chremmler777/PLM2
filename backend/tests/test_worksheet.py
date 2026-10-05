"""Worksheet rows: one per article with the producing tool, revision,
material, paint and DFM status; purchased and tool-only rows marked."""
from datetime import date, datetime

import pytest

from app.models.dfm import DfmEntry, DfmTopic
from app.models.paint import Paint, PartPaint, PartPaintLayer
from app.models.part import Part, PartRelation, PartRevision
from app.models.supplier import Supplier

pytestmark = pytest.mark.asyncio


async def _build(session_factory, seed):
    uid = seed["engineer_id"]
    async with session_factory() as s:
        def part(number, category="article", part_type="internal_mfg", **kw):
            p = Part(project_id=seed["project_id"], part_number=number, name=f"Name {number}",
                     part_type=part_type, item_category=category, created_by=uid, **kw)
            s.add(p)
            return p
        maker = Supplier(name="Formenbau Nord")
        s.add(maker)
        await s.flush()
        lh = part("20-1994-001-0", customer_part_number="206.882.251", tier1_part_number="S00H4X-110",
                  material_source="new", material_new_text="PA6-GF15 acc. VW 50125",
                  colour_code="NM0", grain="KF8")
        rh = part("20-1994-002-0", customer_part_number="206.882.252")
        bought = part("20-1994-050-0", part_type="purchased")
        tool = part("199401", "tool", "purchased", tool_cavities=2, tool_cycle_time_s=55.0, toolmaker_id=maker.id)
        spare = part("199413", "tool", "purchased")
        gauge = part("1994-G1", "gauge", "purchased")
        await s.flush()
        rev = PartRevision(part_id=lh.id, revision_name="E1", phase="review", status="approved",
                           customer_index="001", created_by=uid)
        s.add(rev)
        await s.flush()
        lh.active_revision_id = rev.id
        s.add_all([
            PartRelation(from_part_id=tool.id, to_part_id=lh.id, relation_type="produces", created_by=uid),
            PartRelation(from_part_id=tool.id, to_part_id=rh.id, relation_type="produces", created_by=uid),
            PartRelation(from_part_id=rh.id, to_part_id=lh.id, relation_type="mirror_of", created_by=uid),
        ])
        paint = Paint(organization_id=seed["org_id"], name="Skyscraper base", colour_code="VM0",
                      colour_name="Skyscraper", colour_hex="#aab0b5", created_by=uid)
        s.add(paint)
        await s.flush()
        setup = PartPaint(part_id=rh.id, paint_required=True)
        s.add(setup)
        await s.flush()
        s.add(PartPaintLayer(part_paint_id=setup.id, paint_id=paint.id, layer_order=1))
        topic = DfmTopic(tool_part_id=tool.id, title="Gate position", opened_by=uid)
        s.add(topic)
        await s.flush()
        s.add(DfmEntry(topic_id=topic.id, party="toolmaker", addressed_to=["ktx"], kind="original",
                       recorded_by=uid, recorded_at=datetime(2026, 9, 20), sent_at=date(2026, 9, 20)))
        await s.commit()
        return {"lh": lh.id, "rh": rh.id, "bought": bought.id, "tool": tool.id, "spare": spare.id,
                "gauge": gauge.id, "maker": maker.id}


async def test_rows_carry_article_tool_revision_material_paint_and_dfm(client, eng_auth, seed, session_factory):
    ids = await _build(session_factory, seed)
    r = await client.get(f"/api/v1/projects/{seed['project_id']}/worksheet", headers=eng_auth)
    assert r.status_code == 200, r.text
    rows = {row["part_id"]: row for row in r.json()["rows"]}
    assert set(rows) == {ids["lh"], ids["rh"], ids["bought"], ids["spare"]}  # no gauge, no producing tool row

    lh = rows[ids["lh"]]
    assert lh["row_kind"] == "article"
    assert (lh["customer_part_number"], lh["tier1_part_number"]) == ("206.882.251", "S00H4X-110")
    assert lh["revision"] == {"revision_name": "E1", "customer_index": "001", "phase": "review"}
    assert lh["material"]["material_source"] == "new"
    assert lh["material"]["material_new_text"] == "PA6-GF15 acc. VW 50125"
    assert (lh["colour_code"], lh["grain"]) == ("NM0", "KF8")
    assert lh["paint"] == {"painted": False, "colour": None, "colour_hex": None, "paint_system": None}
    assert lh["tool"] == {"part_id": ids["tool"], "part_number": "199401", "name": "Name 199401", "cavities": 2,
                          "toolmaker_id": ids["maker"], "toolmaker_name": "Formenbau Nord",
                          "cycle_time_s": 55.0, "tonnage_class": None,
                          "machine": None, "shrink_parallel_pct": None, "shrink_normal_pct": None,
                          "shrink_source": None}
    assert lh["material"]["shrinkage"] is None  # not linked to MaterialDB
    assert lh["dfm"] == {"status": "waiting", "waiting_on": ["ktx"], "open_topics": 1}
    assert lh["other_tools"] == []

    rh = rows[ids["rh"]]
    assert rh["mirror_of"] == {"part_id": ids["lh"], "part_number": "20-1994-001-0",
                               "customer_part_number": "206.882.251"}
    assert rh["paint"] == {"painted": True, "colour": "VM0 Skyscraper", "colour_hex": "#aab0b5",
                           "paint_system": "Skyscraper base"}
    assert rh["tool"]["part_id"] == ids["tool"]
    assert (rh["colour_code"], rh["grain"]) == (None, None)
    assert rh["revision"] is None

    assert rows[ids["bought"]]["row_kind"] == "purchased"
    assert rows[ids["bought"]]["tool"] is None and rows[ids["bought"]]["dfm"] is None
    spare = rows[ids["spare"]]
    assert spare["row_kind"] == "tool_only"
    assert spare["tool"]["part_id"] == ids["spare"]
    assert (spare["colour_code"], spare["grain"]) == (None, None)
    assert spare["dfm"] == {"status": "no_topic", "waiting_on": [], "open_topics": 0}


async def test_datasheet_shrinkage_from_materialdb(client, eng_auth, seed, session_factory, monkeypatch):
    from app.services import materialdb_client
    ids = await _build(session_factory, seed)
    async with session_factory() as s:
        lh = await s.get(Part, ids["lh"])
        lh.material_source, lh.materialdb_id, lh.material_label = "materialdb", 88, "EPLAMID 6 H G15 BK005 (research)"
        await s.commit()

    async def fake_fetch(force=False):
        return [{"id": 88, "family": "PA6", "filler_type": "GF", "filler_pct": 15, "props": {
            "shrinkage_flow": {"v": 0.7, "vmax": None, "m": "ISO 294-4", "c": "2 mm"},
            "shrinkage_cross": {"v": 1.0, "vmax": None, "m": "ISO 294-4", "c": "2 mm"},
            "density": {"v": 1.23, "vmax": None}}}]
    monkeypatch.setattr(materialdb_client, "fetch_all", fake_fetch)
    body = (await client.get(f"/api/v1/projects/{seed['project_id']}/worksheet", headers=eng_auth)).json()
    rows = {row["part_id"]: row for row in body["rows"]}
    assert rows[ids["lh"]]["material"]["shrinkage"] == {
        "parallel": {"min": 0.7, "max": None, "method": "ISO 294-4", "condition": "2 mm"},
        "normal": {"min": 1.0, "max": None, "method": "ISO 294-4", "condition": "2 mm"},
        "family": "PA6", "filler_type": "GF", "filler_pct": 15}
    assert body["materialdb_error"] is None

    async def down(force=False):
        raise materialdb_client.MaterialDbUnavailable("MaterialDB is unreachable")
    monkeypatch.setattr(materialdb_client, "fetch_all", down)
    body = (await client.get(f"/api/v1/projects/{seed['project_id']}/worksheet", headers=eng_auth)).json()
    assert body["materialdb_error"] == "MaterialDB is unreachable"
    assert {row["part_id"]: row for row in body["rows"]}[ids["lh"]]["material"]["shrinkage"] is None


async def test_dfm_status_variants(session_factory, seed):
    from app.services.worksheet_service import dfm_status
    uid = seed["engineer_id"]
    t_all = DfmTopic(id=1, tool_part_id=1, title="a", status="open", opened_by=uid)
    t_all.entries = [
        DfmEntry(id=1, topic_id=1, party="toolmaker", addressed_to=["ktx"], kind="original",
                 recorded_by=uid, recorded_at=datetime(2026, 9, 1)),
        DfmEntry(id=2, topic_id=1, party="ktx", addressed_to=["toolmaker"], kind="answer", reply_to_id=1,
                 recorded_by=uid, recorded_at=datetime(2026, 9, 2)),
    ]
    t_empty = DfmTopic(id=2, tool_part_id=1, title="b", status="open", opened_by=uid)
    t_empty.entries = []
    t_done = DfmTopic(id=3, tool_part_id=1, title="c", status="finished_confirmed", opened_by=uid)
    t_done.entries = []
    assert dfm_status([]) == {"status": "no_topic", "waiting_on": [], "open_topics": 0}
    assert dfm_status([t_all])["status"] == "all_answered"
    assert dfm_status([t_all, t_empty]) == {"status": "open", "waiting_on": [], "open_topics": 2}
    assert dfm_status([t_done]) == {"status": "finished", "waiting_on": [], "open_topics": 0}


async def test_empty_project_and_other_org(client, eng_auth, seed, session_factory):
    r = await client.get(f"/api/v1/projects/{seed['project_id']}/worksheet", headers=eng_auth)
    assert r.json() == {"project_id": seed["project_id"], "rows": [], "materialdb_error": None}
    r = await client.get("/api/v1/projects/999999/worksheet", headers=eng_auth)
    assert r.status_code == 404


async def test_tool_shrinkage_carries_its_decision_source(client, eng_auth, seed, session_factory):
    """The chosen shrinkage shows where it came from (the tool's current decision)."""
    ids = await _build(session_factory, seed)
    r = await client.post(f"/api/v1/parts/{ids['tool']}/shrinkage/decisions", headers=eng_auth, json={
        "parallel_pct": 0.65, "normal_pct": 0.65, "source_kind": "ktx_experience",
        "source_label": "KTX tooling note, painted", "rationale": "Painted Bayblend"})
    assert r.status_code == 200, r.text
    rows = {row["part_id"]: row for row in
            (await client.get(f"/api/v1/projects/{seed['project_id']}/worksheet", headers=eng_auth)).json()["rows"]}
    tool = rows[ids["lh"]]["tool"]
    assert (tool["shrink_parallel_pct"], tool["shrink_normal_pct"]) == (0.65, 0.65)
    assert tool["shrink_source"] == "KTX tool experience: KTX tooling note, painted"
    assert rows[ids["spare"]]["tool"]["shrink_source"] is None
