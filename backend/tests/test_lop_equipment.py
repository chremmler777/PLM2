"""Project LOP: a line can be linked to equipment of its project in PLM
(tools, gauges, assembly equipment and EOATs)."""
import pytest

from app.models.part import Part

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


@pytest.fixture
async def equipment(session_factory, lop_project, seed):
    """A tool, its gauge, its EOAT, a station and an article in the LOP project;
    plus a tool of another project."""
    from types import SimpleNamespace
    async with session_factory() as s:
        def part(number, name, category, project_id=lop_project.id):
            p = Part(project_id=project_id, part_number=number, name=name, part_type="internal_mfg",
                     created_by=seed["admin_id"],
                     item_category=category)
            s.add(p)
            return p
        tool = part("3345", "UBV Mitte", "tool")
        gauge = part("3345-40", "Gauge UBV Mitte", "gauge")
        eoat = part("3345-10", "EOAT", "assembly_equipment")
        station = part("3345-20", "Degate station", "assembly_equipment")
        article = part("21-3345-0001", "UBV Mitte part", "article")
        other = part("9999", "Other project tool", "tool", project_id=seed["project_id"])
        await s.commit()
        return SimpleNamespace(tool=tool.id, gauge=gauge.id, eoat=eoat.id, station=station.id,
                               article=article.id, other=other.id)


def _lines(pid):
    return f"{BASE}/projects/{pid}/lines"


async def test_the_pick_list_holds_tools_gauges_and_equipment_of_the_project(client, pm_auth, lop_project, equipment):
    r = await client.get(f"{BASE}/projects/{lop_project.id}/equipment", headers=pm_auth)
    assert r.status_code == 200, r.text
    got = {e["part_number"]: e for e in r.json()}
    assert set(got) == {"3345", "3345-40", "3345-10", "3345-20", "21-3345-0001"}   # not the other project
    assert got["21-3345-0001"]["kind"] == "article" and got["21-3345-0001"]["tool_number"] is None
    assert got["3345"]["kind"] == "tool" and got["3345-40"]["kind"] == "gauge"
    assert got["3345-10"]["kind"] == "eoat" and got["3345-20"]["kind"] == "assembly_equipment"
    assert got["3345-10"]["tool_number"] == "3345" and got["3345"]["tool_number"] == "3345"


async def test_a_task_is_created_with_equipment(client, pm_auth, lop_project, equipment):
    r = await client.post(_lines(lop_project.id), headers=pm_auth,
                          json={"title": "Gauge R&R", "equipment_ids": [equipment.gauge, equipment.tool, equipment.gauge]})
    assert r.status_code == 201, r.text
    eq = r.json()["equipment"]
    assert [e["part_number"] for e in eq] == ["3345", "3345-40"]            # by number, once each
    assert eq[1] == {"id": equipment.gauge, "part_number": "3345-40", "name": "Gauge UBV Mitte",
                     "kind": "gauge", "tool_number": "3345", "customer_part_number": None}


async def test_no_equipment_is_an_empty_list(client, pm_auth, line):
    got = (await client.get(f"{BASE}/lines/{line}/history", headers=pm_auth))
    assert got.status_code == 200
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"equipment_ids": []})
    assert r.json()["equipment"] == []


async def test_only_equipment_of_the_same_project_can_be_linked(client, pm_auth, lop_project, equipment):
    for bad in (equipment.other, 987654):
        r = await client.post(_lines(lop_project.id), headers=pm_auth,
                              json={"title": "x", "equipment_ids": [bad]})
        assert r.status_code == 400, bad
        assert "articles, tools, gauges and assembly equipment of this project" in r.json()["detail"]


async def test_a_line_is_linked_to_an_article(client, pm_auth, lop_project, equipment):
    r = await client.post(_lines(lop_project.id), headers=pm_auth,
                          json={"title": "Sink mark on A-surface", "equipment_ids": [equipment.article, equipment.tool]})
    assert r.status_code == 201, r.text
    assert [(e["kind"], e["part_number"]) for e in r.json()["equipment"]] == [
        ("article", "21-3345-0001"), ("tool", "3345")]


async def test_pm_changes_the_equipment_and_history_says_so(client, pm_auth, line, equipment):
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"equipment_ids": [equipment.eoat]})
    assert [e["part_number"] for e in r.json()["equipment"]] == ["3345-10"]
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"equipment_ids": [equipment.station]})
    assert [e["part_number"] for e in r.json()["equipment"]] == ["3345-20"]
    hist = [h for h in (await client.get(f"{BASE}/lines/{line}/history", headers=pm_auth)).json()
            if h.get("field") == "equipment"]
    assert sorted((h["old_value"] or "", h["new_value"] or "") for h in hist) == sorted([
        ("", "3345-10 EOAT"), ("3345-10 EOAT", ""), ("", "3345-20 Degate station")])
    before = len((await client.get(f"{BASE}/lines/{line}/history", headers=pm_auth)).json())
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"equipment_ids": [equipment.station]})
    assert len((await client.get(f"{BASE}/lines/{line}/history", headers=pm_auth)).json()) == before


async def test_the_responsible_cannot_change_equipment(client, quality_auth, line, equipment):
    r = await client.patch(f"{BASE}/lines/{line}", headers=quality_auth, json={"equipment_ids": [equipment.tool]})
    assert r.status_code == 403


async def test_the_project_list_and_the_excel_carry_the_equipment(client, pm_auth, lop_project, line, equipment):
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"equipment_ids": [equipment.gauge, equipment.tool]})
    got = (await client.get(f"{BASE}/projects/{lop_project.id}", headers=pm_auth)).json()
    ln = next(x for x in got["lines"] if x["id"] == line)
    assert [e["part_number"] for e in ln["equipment"]] == ["3345", "3345-40"]
    from io import BytesIO
    from openpyxl import load_workbook
    x = await client.get(f"{BASE}/projects/{lop_project.id}/export.xlsx", headers=pm_auth)
    ws = load_workbook(BytesIO(x.content)).active
    rows = list(ws.iter_rows(values_only=True))
    head = next(list(r) for r in rows if r[0] == "No.")       # row 1 is a note when PDB is not configured
    row = next(r for r in rows if r[0] == line)
    assert row[head.index("Tool")] == "3345, 3345-40"
