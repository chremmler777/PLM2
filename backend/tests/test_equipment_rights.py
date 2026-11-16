"""Rights by item category (app/services/equipment_rights.py): gauges belong to APQP and
the Project Manager, assembly equipment and EOATs to the Manufacturing Engineer and the
Project Manager, tools to the Tool Engineer; an admin may do all of it, an admin acting
as a department only what that department may. Articles have no rule."""
import pytest

from app.services.equipment_rights import ASSEMBLY_EQUIPMENT_EDIT_DENIED, GAUGE_EDIT_DENIED
from app.services.tool_rights import TOOL_EDIT_DENIED
from tests.conftest import make_department_member

pytestmark = pytest.mark.asyncio

ACTS_AS = "X-Acts-As-Department"


async def _create(client, auth, seed, number, category):
    return await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": f"{category} {number}",
        "part_type": "internal_mfg", "data_classification": "confidential",
        "item_category": category}, headers=auth)


async def _made(client, auth, seed, number, category) -> int:
    res = await _create(client, auth, seed, number, category)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _link(client, auth, from_id, to_id, relation_type):
    return await client.post(f"/api/v1/parts/{from_id}/relations",
                             json={"to_part_id": to_id, "relation_type": relation_type}, headers=auth)


async def _join(session_factory, seed, department):
    return await make_department_member(session_factory, seed["engineer_id"], department)


# ---- create ----------------------------------------------------------------

async def test_without_a_department_only_articles_can_be_created(client, eng_auth, seed):
    assert (await _create(client, eng_auth, seed, "20-0001", "article")).status_code in (200, 201)
    for number, category, text in [("3345-40", "gauge", GAUGE_EDIT_DENIED),
                                   ("3345-20", "assembly_equipment", ASSEMBLY_EQUIPMENT_EDIT_DENIED),
                                   ("3345", "tool", TOOL_EDIT_DENIED)]:
        res = await _create(client, eng_auth, seed, number, category)
        assert res.status_code == 403, (category, res.text)
        assert res.json()["detail"] == text


@pytest.mark.parametrize("department,allowed", [
    ("APQP", {"gauge"}),
    ("Project Manager", {"gauge", "assembly_equipment"}),
    ("Manufacturing Engineer", {"assembly_equipment"}),
    ("Tool Engineer", {"tool"}),
    ("Quality", set()),
])
async def test_create_matrix_by_department(client, eng_auth, seed, session_factory, department, allowed):
    await _join(session_factory, seed, department)
    for number, category in [("3345-40", "gauge"), ("3345-10", "assembly_equipment"), ("3345", "tool")]:
        res = await _create(client, eng_auth, seed, number, category)
        expected = (200, 201) if category in allowed else (403,)
        assert res.status_code in expected, (department, category, res.text)


async def test_admin_creates_everything(client, admin_auth, seed):
    for number, category in [("3345", "tool"), ("3345-40", "gauge"), ("3345-10", "assembly_equipment")]:
        assert (await _create(client, admin_auth, seed, number, category)).status_code in (200, 201)


# ---- update ----------------------------------------------------------------

async def test_update_needs_the_right_of_the_items_category(client, eng_auth, admin_auth, seed, session_factory):
    gauge = await _made(client, admin_auth, seed, "3345-40", "gauge")
    station = await _made(client, admin_auth, seed, "3345-20", "assembly_equipment")
    article = await _made(client, admin_auth, seed, "20-0001", "article")

    res = await client.put(f"/api/v1/parts/{gauge}", json={"name": "x"}, headers=eng_auth)
    assert res.status_code == 403 and res.json()["detail"] == GAUGE_EDIT_DENIED
    res = await client.put(f"/api/v1/parts/{station}", json={"name": "x"}, headers=eng_auth)
    assert res.status_code == 403 and res.json()["detail"] == ASSEMBLY_EQUIPMENT_EDIT_DENIED
    assert (await client.put(f"/api/v1/parts/{article}", json={"name": "x"}, headers=eng_auth)).status_code == 200
    # an article cannot be turned into a gauge to get around the create rule
    res = await client.put(f"/api/v1/parts/{article}", json={"item_category": "gauge"}, headers=eng_auth)
    assert res.status_code == 403

    await _join(session_factory, seed, "APQP")
    assert (await client.put(f"/api/v1/parts/{gauge}", json={"name": "Gauge A", "change_kind": "correction"}, headers=eng_auth)).status_code == 200
    assert (await client.put(f"/api/v1/parts/{station}", json={"name": "x"}, headers=eng_auth)).status_code == 403

    await _join(session_factory, seed, "Manufacturing Engineer")
    assert (await client.put(f"/api/v1/parts/{station}", json={"name": "Degate", "change_kind": "correction"}, headers=eng_auth)).status_code == 200


# ---- relations -------------------------------------------------------------

async def test_relations_need_the_right_of_their_kind(client, eng_auth, admin_auth, seed, session_factory):
    tool = await _made(client, admin_auth, seed, "3345", "tool")
    gauge = await _made(client, admin_auth, seed, "3345-40", "gauge")
    eoat = await _made(client, admin_auth, seed, "3345-10", "assembly_equipment")
    article = await _made(client, admin_auth, seed, "20-0001", "article")
    other = await _made(client, admin_auth, seed, "20-0002", "article")

    # no department: none of the equipment links, but the open kinds stay open
    for from_id, to_id, kind, text in [(gauge, article, "checks", GAUGE_EDIT_DENIED),
                                       (eoat, article, "assembles", ASSEMBLY_EQUIPMENT_EDIT_DENIED),
                                       (gauge, tool, "serves", GAUGE_EDIT_DENIED),
                                       (eoat, tool, "serves", ASSEMBLY_EQUIPMENT_EDIT_DENIED),
                                       (tool, article, "produces", TOOL_EDIT_DENIED)]:
        res = await _link(client, eng_auth, from_id, to_id, kind)
        assert res.status_code == 403 and res.json()["detail"] == text, (kind, res.text)
    assert (await _link(client, eng_auth, article, other, "related")).status_code == 201

    # APQP: the gauge's links only
    await _join(session_factory, seed, "APQP")
    checks = await _link(client, eng_auth, gauge, article, "checks")
    assert checks.status_code == 201, checks.text
    assert (await _link(client, eng_auth, gauge, tool, "serves")).status_code == 201
    assert (await _link(client, eng_auth, eoat, article, "assembles")).status_code == 403
    assert (await _link(client, eng_auth, eoat, tool, "serves")).status_code == 403
    assert (await _link(client, eng_auth, tool, article, "produces")).status_code == 403

    # removing follows the same rule
    assembles = await _link(client, admin_auth, eoat, article, "assembles")
    assert assembles.status_code == 201
    res = await client.delete(f"/api/v1/parts/relations/{assembles.json()['id']}", headers=eng_auth)
    assert res.status_code == 403 and res.json()["detail"] == ASSEMBLY_EQUIPMENT_EDIT_DENIED
    assert (await client.delete(f"/api/v1/parts/relations/{checks.json()['id']}", headers=eng_auth)).status_code == 200

    # Manufacturing Engineer: the equipment's links
    await _join(session_factory, seed, "Manufacturing Engineer")
    assert (await _link(client, eng_auth, eoat, tool, "serves")).status_code == 201
    assert (await client.delete(f"/api/v1/parts/relations/{assembles.json()['id']}", headers=eng_auth)).status_code == 200
    assert (await _link(client, eng_auth, eoat, article, "assembles")).status_code == 201


async def test_deleting_a_checks_link_without_the_right_is_refused(client, eng_auth, admin_auth, seed):
    gauge = await _made(client, admin_auth, seed, "3345-40", "gauge")
    article = await _made(client, admin_auth, seed, "20-0001", "article")
    rel = await _link(client, admin_auth, gauge, article, "checks")
    res = await client.delete(f"/api/v1/parts/relations/{rel.json()['id']}", headers=eng_auth)
    assert res.status_code == 403 and res.json()["detail"] == GAUGE_EDIT_DENIED


# ---- /auth/me and acts-as --------------------------------------------------

async def _flags(client, auth):
    me = (await client.get("/api/v1/auth/me", headers=auth)).json()
    return me["can_edit_tools"], me["can_edit_gauges"], me["can_edit_assembly_equipment"]


async def test_me_reports_the_rights(client, eng_auth, admin_auth, seed, session_factory):
    assert await _flags(client, admin_auth) == (True, True, True)
    assert await _flags(client, eng_auth) == (False, False, False)
    await _join(session_factory, seed, "APQP")
    assert await _flags(client, eng_auth) == (False, True, False)
    await _join(session_factory, seed, "Manufacturing Engineer")
    assert await _flags(client, eng_auth) == (False, True, True)


async def test_project_manager_has_both_equipment_rights(client, eng_auth, seed, session_factory):
    await _join(session_factory, seed, "Project Manager")
    assert await _flags(client, eng_auth) == (False, True, True)


async def test_admin_acting_as_a_department_counts_as_that_department(client, admin_auth, seed, session_factory):
    apqp = await make_department_member(session_factory, seed["admin_id"], "APQP")
    me_dept = await make_department_member(session_factory, seed["admin_id"], "Manufacturing Engineer")
    quality = await make_department_member(session_factory, seed["admin_id"], "Quality")
    as_apqp = {**admin_auth, ACTS_AS: str(apqp)}
    as_me = {**admin_auth, ACTS_AS: str(me_dept)}
    as_quality = {**admin_auth, ACTS_AS: str(quality)}

    assert await _flags(client, as_apqp) == (False, True, False)
    assert await _flags(client, as_me) == (False, False, True)
    assert await _flags(client, as_quality) == (False, False, False)

    assert (await _create(client, as_apqp, seed, "3345-40", "gauge")).status_code in (200, 201)
    res = await _create(client, as_apqp, seed, "3345-10", "assembly_equipment")
    assert res.status_code == 403 and res.json()["detail"] == ASSEMBLY_EQUIPMENT_EDIT_DENIED
    assert (await _create(client, as_me, seed, "3345-10", "assembly_equipment")).status_code in (200, 201)
    res = await _create(client, as_me, seed, "3345-41", "gauge")
    assert res.status_code == 403 and res.json()["detail"] == GAUGE_EDIT_DENIED
    assert (await _create(client, as_quality, seed, "3345", "tool")).status_code == 403
