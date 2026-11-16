"""Equipment rework (app/services/equipment_service.py): a gauge, station or EOAT may
serve one tool, several or none; assembles links carry an amount; every change lands
in the history with a kind (correction, change, obsolete, reactivated); obsolete
items are locked and leave the pick lists; numbers are unique across projects."""
import pytest

from app.models.entities import Project
from app.services import equipment_service as es
from app.services.equipment_rights import ASSEMBLY_EQUIPMENT_EDIT_DENIED, GAUGE_EDIT_DENIED
from app.services.lop_service import LopService
from tests.conftest import make_department_member

pytestmark = pytest.mark.asyncio


async def _create(client, auth, project_id, number, category, **extra):
    return await client.post("/api/v1/parts", json={
        "project_id": project_id, "part_number": number, "name": f"{category} {number}",
        "part_type": "internal_mfg", "data_classification": "confidential",
        "item_category": category, **extra}, headers=auth)


async def _made(client, auth, seed, number, category, **extra) -> int:
    res = await _create(client, auth, seed["project_id"], number, category, **extra)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _link(client, auth, from_id, to_id, kind, **extra):
    return await client.post(f"/api/v1/parts/{from_id}/relations",
                             json={"to_part_id": to_id, "relation_type": kind, **extra}, headers=auth)


async def _history(client, auth, part_id):
    res = await client.get(f"/api/v1/parts/{part_id}/history", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _relations(client, auth, part_id):
    return (await client.get(f"/api/v1/parts/{part_id}/relations", headers=auth)).json()


# ---- tool optional, several tools ------------------------------------------

async def test_equipment_and_gauge_without_a_tool_are_complete_items(client, admin_auth, seed):
    station = await _made(client, admin_auth, seed, "ASSY-OP-10", "assembly_equipment")
    gauge = await _made(client, admin_auth, seed, "ASSY-GAUGE-1", "gauge")
    article = await _made(client, admin_auth, seed, "50-2277-001-0", "article")
    assert (await _link(client, admin_auth, station, article, "assembles")).status_code == 201
    assert (await _link(client, admin_auth, gauge, article, "checks")).status_code == 201
    assert [r["relation_type"] for r in await _relations(client, admin_auth, station)] == ["assembles"]


async def test_equipment_can_serve_several_tools_and_drop_one(client, admin_auth, seed):
    t1 = await _made(client, admin_auth, seed, "3345", "tool")
    t2 = await _made(client, admin_auth, seed, "3346", "tool")
    eoat = await _made(client, admin_auth, seed, "3345-10", "assembly_equipment")
    first = await _link(client, admin_auth, eoat, t1, "serves")
    assert first.status_code == 201 and first.json()["quantity"] is None
    assert (await _link(client, admin_auth, eoat, t2, "serves")).status_code == 201
    assert sorted(r["other_part_number"] for r in await _relations(client, admin_auth, eoat)) == ["3345", "3346"]
    assert (await client.delete(f"/api/v1/parts/relations/{first.json()['id']}", headers=admin_auth)).status_code == 200
    assert [r["other_part_number"] for r in await _relations(client, admin_auth, eoat)] == ["3346"]
    texts = [h["description"] for h in await _history(client, admin_auth, eoat)]
    assert texts[:3] == ["Tool 3345 removed", "Tool 3346 added", "Tool 3345 added"]


# ---- amounts ---------------------------------------------------------------

async def test_assembles_carries_an_amount_checks_does_not(client, admin_auth, seed):
    station = await _made(client, admin_auth, seed, "3345-20", "assembly_equipment")
    gauge = await _made(client, admin_auth, seed, "3345-40", "gauge")
    a1 = await _made(client, admin_auth, seed, "50-2277-001-0", "article")
    a2 = await _made(client, admin_auth, seed, "50-2277-002-0", "article")

    default = await _link(client, admin_auth, station, a1, "assembles")
    assert default.status_code == 201 and default.json()["quantity"] == 1
    two = await _link(client, admin_auth, station, a2, "assembles", quantity=2)
    assert two.status_code == 201 and two.json()["quantity"] == 2
    for bad in (0, -1):
        res = await _link(client, admin_auth, station, gauge, "assembles", quantity=bad)
        assert res.status_code == 400 and res.json()["detail"] == es.QUANTITY_INVALID

    checks = await _link(client, admin_auth, gauge, a1, "checks", quantity=5)
    assert checks.status_code == 201 and checks.json()["quantity"] is None

    # change the amount: logged, must stay above 0, only on assembles
    url = f"/api/v1/parts/relations/{two.json()['id']}"
    res = await client.patch(url, json={"quantity": 0.5}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["quantity"] == 0.5
    res = await client.patch(url, json={"quantity": 0}, headers=admin_auth)
    assert res.status_code == 400 and res.json()["detail"] == es.QUANTITY_INVALID
    res = await client.patch(f"/api/v1/parts/relations/{checks.json()['id']}", json={"quantity": 2}, headers=admin_auth)
    assert res.status_code == 400 and res.json()["detail"] == es.QUANTITY_ONLY_ASSEMBLES

    log = await _history(client, admin_auth, station)
    assert [h["description"] for h in log] == [
        "Article 50-2277-002-0 quantity 2 -> 0.5",
        "Article 50-2277-002-0 added, quantity 2",
        "Article 50-2277-001-0 added, quantity 1",
    ]
    assert {h["kind"] for h in log} == {"change"}
    assert [h["description"] for h in await _history(client, admin_auth, gauge)][0] == "Article 50-2277-001-0 added"

    # the article's structure row carries the amount
    structure = (await client.get(f"/api/v1/parts/project/{seed['project_id']}/structure", headers=admin_auth)).json()
    art2 = next(a for a in structure["articles"] if a["part_id"] == a2)
    assert art2["obsolete_at"] is None
    assert [(r["relation_type"], r["quantity"], r["obsolete_at"]) for r in art2["related"]] == [("assembles", 0.5, None)]


# ---- edit with a kind ------------------------------------------------------

async def test_edit_needs_a_kind_and_logs_one_row_per_field(client, admin_auth, seed):
    gauge = await _made(client, admin_auth, seed, "3345-40", "gauge", calibration_interval_months=12)
    url = f"/api/v1/parts/{gauge}"

    res = await client.put(url, json={"name": "Checking fixture"}, headers=admin_auth)
    assert res.status_code == 400 and res.json()["detail"] == es.KIND_MISSING
    res = await client.put(url, json={"name": "Checking fixture", "change_kind": "tweak"}, headers=admin_auth)
    assert res.status_code == 400 and res.json()["detail"] == es.KIND_MISSING
    res = await client.put(url, json={"name": "Checking fixture", "change_kind": "change"}, headers=admin_auth)
    assert res.status_code == 400 and res.json()["detail"] == es.NOTE_MISSING
    assert await _history(client, admin_auth, gauge) == []

    # a correction needs no note; three fields changed, one unchanged -> three rows
    res = await client.put(url, json={
        "name": "Checking fixture", "part_number": "3345-41", "description": "CMM fixture",
        "calibration_interval_months": 12, "change_kind": "correction"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["name"], body["part_number"], body["description"]) == ("Checking fixture", "3345-41", "CMM fixture")
    log = await _history(client, admin_auth, gauge)
    assert sorted(h["field"] for h in log) == ["description", "name", "part_number"]
    assert {h["kind"] for h in log} == {"correction"}
    number = next(h for h in log if h["field"] == "part_number")
    assert (number["old_value"], number["new_value"], number["by_name"]) == ("3345-40", "3345-41", "Admin")

    # a change with its note
    res = await client.put(url, json={"calibration_interval_months": 6, "change_kind": "change",
                                      "change_note": "new customer requirement"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["calibration_interval_months"] == 6
    newest = (await _history(client, admin_auth, gauge))[0]
    assert (newest["kind"], newest["field"], newest["old_value"], newest["new_value"], newest["note"]) == (
        "change", "calibration_interval_months", "12", "6", "new customer requirement")


async def test_moving_and_calibrating_need_no_kind_and_other_categories_are_untouched(client, admin_auth, seed):
    gauge = await _made(client, admin_auth, seed, "3345-40", "gauge", calibration_interval_months=6)
    res = await client.put(f"/api/v1/parts/{gauge}", json={"last_calibrated_at": "2026-06-01T00:00:00"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["next_calibration_due"] is not None
    assert (await client.put(f"/api/v1/parts/{gauge}", json={"parent_part_id": None}, headers=admin_auth)).status_code == 200

    article = await _made(client, admin_auth, seed, "50-2277-001-0", "article")
    tool = await _made(client, admin_auth, seed, "3345", "tool")
    assert (await client.put(f"/api/v1/parts/{article}", json={"name": "x"}, headers=admin_auth)).status_code == 200
    assert (await client.put(f"/api/v1/parts/{tool}", json={"name": "y"}, headers=admin_auth)).status_code == 200
    # the number of an article or tool is not changed through this call
    res = await client.put(f"/api/v1/parts/{tool}", json={"part_number": "9999"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["part_number"] == "3345"


# ---- obsolete / reactivate -------------------------------------------------

async def test_obsolete_locks_the_item_and_reactivate_opens_it(client, admin_auth, seed):
    station = await _made(client, admin_auth, seed, "3345-20", "assembly_equipment")
    tool = await _made(client, admin_auth, seed, "3345", "tool")
    a1 = await _made(client, admin_auth, seed, "50-2277-001-0", "article")
    a2 = await _made(client, admin_auth, seed, "50-2277-002-0", "article")
    linked = await _link(client, admin_auth, station, a1, "assembles")

    res = await client.post(f"/api/v1/parts/{station}/obsolete", json={}, headers=admin_auth)
    assert res.status_code == 400 and res.json()["detail"] == es.OBSOLETE_NOTE_MISSING
    res = await client.post(f"/api/v1/parts/{station}/obsolete", json={"note": "replaced by 3345-21"}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["obsolete_at"] is not None
    assert (await client.get(f"/api/v1/parts/{station}", headers=admin_auth)).json()["obsolete_at"] is not None
    assert (await client.post(f"/api/v1/parts/{station}/obsolete", json={"note": "again"}, headers=admin_auth)).status_code == 400

    # locked: no edit, no new link (either direction), no amount change, no unlink
    locked = [
        await client.put(f"/api/v1/parts/{station}", json={"name": "x", "change_kind": "correction"}, headers=admin_auth),
        await _link(client, admin_auth, station, a2, "assembles"),
        await _link(client, admin_auth, station, tool, "serves"),
        await _link(client, admin_auth, a2, station, "related"),
        await client.patch(f"/api/v1/parts/relations/{linked.json()['id']}", json={"quantity": 3}, headers=admin_auth),
        await client.delete(f"/api/v1/parts/relations/{linked.json()['id']}", headers=admin_auth),
    ]
    assert [r.status_code for r in locked] == [400] * 6
    assert {r.json()["detail"] for r in locked} == {es.OBSOLETE_LOCKED}
    # the article still shows its obsolete station
    rel = (await _relations(client, admin_auth, a1))[0]
    assert rel["other_obsolete_at"] is not None

    res = await client.post(f"/api/v1/parts/{station}/reactivate", json={}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["obsolete_at"] is None
    assert (await client.post(f"/api/v1/parts/{station}/reactivate", json={}, headers=admin_auth)).status_code == 400
    assert (await _link(client, admin_auth, station, a2, "assembles")).status_code == 201

    log = await _history(client, admin_auth, station)
    assert [(h["kind"], h["description"]) for h in log[:3]] == [
        ("change", "Article 50-2277-002-0 added, quantity 1"),
        ("reactivated", "Reactivated"),
        ("obsolete", "Marked obsolete: replaced by 3345-21"),
    ]
    assert [h["id"] for h in log] == sorted((h["id"] for h in log), reverse=True)   # newest first


async def test_only_equipment_can_be_obsolete(client, admin_auth, seed):
    tool = await _made(client, admin_auth, seed, "3345", "tool")
    article = await _made(client, admin_auth, seed, "50-2277-001-0", "article")
    for pid in (tool, article):
        res = await client.post(f"/api/v1/parts/{pid}/obsolete", json={"note": "x"}, headers=admin_auth)
        assert res.status_code == 400 and res.json()["detail"] == es.NOT_EQUIPMENT
    assert (await client.post("/api/v1/parts/99999/obsolete", json={"note": "x"}, headers=admin_auth)).status_code == 404
    assert (await client.get("/api/v1/parts/99999/history", headers=admin_auth)).status_code == 404


# ---- numbers ---------------------------------------------------------------

async def _other_project(session_factory, seed) -> int:
    async with session_factory() as s:
        first = await s.get(Project, seed["project_id"])
        other = Project(plant_id=first.plant_id, name="Other", code="other", status="active")
        s.add(other)
        await s.commit()
        return other.id


async def test_next_equipment_number_looks_across_projects(client, admin_auth, seed, session_factory):
    tool = await _made(client, admin_auth, seed, "3345", "tool")
    other = await _other_project(session_factory, seed)
    url = "/api/v1/parts/next-equipment-number"

    async def nxt(family):
        res = await client.get(url, params={"tool_id": tool, "family": family}, headers=admin_auth)
        assert res.status_code == 200, res.text
        return res.json()["number"]

    assert [await nxt(f) for f in (1, 2, 3, 4)] == ["3345-10", "3345-20", "3345-30", "3345-40"]
    await _made(client, admin_auth, seed, "3345-40", "gauge")
    assert (await _create(client, admin_auth, other, "3345-41", "gauge")).status_code in (200, 201)
    assert await nxt(4) == "3345-42"
    assert await nxt(1) == "3345-10"

    for family in (6, 7, 8):       # 6 and 7 hang on the project code, not on a tool
        assert (await client.get(url, params={"tool_id": tool, "family": family}, headers=admin_auth)).status_code == 400
    gauge_as_tool = await client.get(url, params={"tool_id": 99999, "family": 4}, headers=admin_auth)
    assert gauge_as_tool.status_code == 404


async def test_next_equipment_number_is_null_when_the_family_is_full(client, admin_auth, seed):
    tool = await _made(client, admin_auth, seed, "3345", "tool")
    for i in range(10):
        await _made(client, admin_auth, seed, f"3345-4{i}", "gauge")
    res = await client.get("/api/v1/parts/next-equipment-number", params={"tool_id": tool, "family": 4}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["number"] is None


async def test_duplicate_equipment_number_is_refused_in_plain_words(client, admin_auth, seed, session_factory):
    await _made(client, admin_auth, seed, "3345-40", "gauge")
    other = await _other_project(session_factory, seed)
    for project_id, category in ((seed["project_id"], "gauge"), (other, "assembly_equipment")):
        res = await _create(client, admin_auth, project_id, "3345-40", category)
        assert res.status_code == 409
        assert res.json()["detail"] == "The number 3345-40 is already in use. Pick another number."
    # renaming onto a taken number is refused the same way
    second = await _made(client, admin_auth, seed, "3345-41", "gauge")
    res = await client.put(f"/api/v1/parts/{second}", json={"part_number": "3345-40", "change_kind": "correction"},
                           headers=admin_auth)
    assert res.status_code == 400 and "already in use" in res.json()["detail"]


# ---- LOP pick list ---------------------------------------------------------

async def test_obsolete_items_leave_the_lop_pick_list(client, admin_auth, seed, session_factory):
    gauge = await _made(client, admin_auth, seed, "3345-40", "gauge")
    keep = await _made(client, admin_auth, seed, "3345-41", "gauge")
    async with session_factory() as s:
        assert {e["id"] for e in await LopService.project_equipment(s, seed["project_id"])} == {gauge, keep}
    await client.post(f"/api/v1/parts/{gauge}/obsolete", json={"note": "scrapped"}, headers=admin_auth)
    async with session_factory() as s:
        assert {e["id"] for e in await LopService.project_equipment(s, seed["project_id"])} == {keep}


# ---- rights ----------------------------------------------------------------

async def test_rights_on_the_new_endpoints(client, eng_auth, admin_auth, seed, session_factory):
    gauge = await _made(client, admin_auth, seed, "3345-40", "gauge")
    station = await _made(client, admin_auth, seed, "3345-20", "assembly_equipment")
    article = await _made(client, admin_auth, seed, "50-2277-001-0", "article")
    rel = (await _link(client, admin_auth, station, article, "assembles")).json()["id"]

    async def attempts(auth):
        return [
            (await client.post(f"/api/v1/parts/{gauge}/obsolete", json={"note": "x"}, headers=auth)),
            (await client.post(f"/api/v1/parts/{station}/obsolete", json={"note": "x"}, headers=auth)),
            (await client.patch(f"/api/v1/parts/relations/{rel}", json={"quantity": 2}, headers=auth)),
        ]

    denied = await attempts(eng_auth)
    assert [r.status_code for r in denied] == [403, 403, 403]
    assert [r.json()["detail"] for r in denied] == [
        GAUGE_EDIT_DENIED, ASSEMBLY_EQUIPMENT_EDIT_DENIED, ASSEMBLY_EQUIPMENT_EDIT_DENIED]
    # reading the history and asking for a number need no right
    assert (await client.get(f"/api/v1/parts/{gauge}/history", headers=eng_auth)).status_code == 200

    await make_department_member(session_factory, seed["engineer_id"], "APQP")
    assert [r.status_code for r in await attempts(eng_auth)] == [200, 403, 403]
    res = await client.post(f"/api/v1/parts/{station}/reactivate", json={}, headers=eng_auth)
    assert res.status_code == 403
    assert (await client.post(f"/api/v1/parts/{gauge}/reactivate", json={}, headers=eng_auth)).status_code == 200

    await make_department_member(session_factory, seed["engineer_id"], "Manufacturing Engineer")
    res = await client.patch(f"/api/v1/parts/relations/{rel}", json={"quantity": 2}, headers=eng_auth)
    assert res.status_code == 200 and res.json()["quantity"] == 2
    assert (await client.post(f"/api/v1/parts/{station}/obsolete", json={"note": "x"}, headers=eng_auth)).status_code == 200


# ---- numbers without a tool: <project code>-6x / -7x ------------------------

async def test_next_number_without_a_tool_hangs_on_the_project_code(client, admin_auth, seed, session_factory):
    url = "/api/v1/parts/next-equipment-number"
    pid = seed["project_id"]          # project code "proj"

    async def nxt(family):
        res = await client.get(url, params={"project_id": pid, "family": family}, headers=admin_auth)
        assert res.status_code == 200, res.text
        return res.json()["number"]

    assert (await nxt(6), await nxt(7)) == ("proj-60", "proj-70")
    await _made(client, admin_auth, seed, "proj-60", "assembly_equipment")
    other = await _other_project(session_factory, seed)
    assert (await _create(client, admin_auth, other, "proj-61", "assembly_equipment")).status_code in (200, 201)
    assert await nxt(6) == "proj-62"          # the other project's number counts too
    assert await nxt(7) == "proj-70"          # gauges have their own ten numbers

    for family in (1, 4, 8):
        res = await client.get(url, params={"project_id": pid, "family": family}, headers=admin_auth)
        assert res.status_code == 400
    assert (await client.get(url, params={"family": 6}, headers=admin_auth)).status_code == 400
    assert (await client.get(url, params={"project_id": 99999, "family": 6}, headers=admin_auth)).status_code == 404


async def test_next_number_without_a_tool_is_null_when_all_ten_are_used(client, admin_auth, seed):
    for i in range(10):
        await _made(client, admin_auth, seed, f"proj-7{i}", "gauge")
    res = await client.get("/api/v1/parts/next-equipment-number",
                           params={"project_id": seed["project_id"], "family": 7}, headers=admin_auth)
    assert res.status_code == 200 and res.json()["number"] is None
    res = await client.get("/api/v1/parts/next-equipment-number",
                           params={"project_id": seed["project_id"], "family": 6}, headers=admin_auth)
    assert res.json()["number"] == "proj-60"


async def test_a_project_number_is_never_taken_for_equipment_of_a_tool(client, admin_auth, seed, session_factory):
    """Tool 1748 exists; 1748-60 and 1748-70 are no-tool items of project 1748, not its equipment."""
    from app.models.part import Part
    from app.services.lop_service import equipment_dict
    from app.services.process_flow_service import ProcessFlowService
    tool = await _made(client, admin_auth, seed, "1748", "tool")
    station = await _made(client, admin_auth, seed, "1748-60", "assembly_equipment")
    gauge = await _made(client, admin_auth, seed, "1748-70", "gauge")
    eoat = await _made(client, admin_auth, seed, "1748-10", "assembly_equipment")
    async with session_factory() as s:
        dicts = {pid: equipment_dict(await s.get(Part, pid)) for pid in (station, gauge, eoat)}
        assert (dicts[station]["kind"], dicts[station]["tool_number"]) == ("assembly_equipment", None)
        assert (dicts[gauge]["kind"], dicts[gauge]["tool_number"]) == ("gauge", None)
        assert (dicts[eoat]["kind"], dicts[eoat]["tool_number"]) == ("eoat", "1748")
        # no serves link: the process flow finds no tool for them and lists them under none
        assert await ProcessFlowService._resolve_tool(s, await s.get(Part, station)) is None
        assert await ProcessFlowService.stations_for(s, await s.get(Part, tool)) == []
    flow = await client.get(f"/api/v1/parts/{station}/process-flow", headers=admin_auth)
    if flow.status_code == 200:
        assert flow.json()["stations"] == []
    # linked to a tool on purpose it shows as an assembly operation, without an error
    assert (await _link(client, admin_auth, station, tool, "serves")).status_code == 201
    async with session_factory() as s:
        stations = await ProcessFlowService.stations_for(s, await s.get(Part, tool))
        assert [(st["part_number"], st["kind"]) for st in stations] == [("1748-60", "assembly_operation")]
