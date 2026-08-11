"""Assessment buckets: each routed department gets the objects in ITS domain,
derived from the impacted set through the existing part relations."""
import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeImpactedItem, ChangeRequest
from app.models.part import Part, PartRelation
from app.models.workflow import Department

pytestmark = pytest.mark.asyncio

DEPTS = ["Tool Engineer", "Manufacturing Engineer", "APQP", "Development", "Quality"]


@pytest.fixture
async def world(session_factory, seed):
    """An impacted article, the tool that produces it, and the station + gauge
    that serve that tool (the real numbering shape: stations and gauges hang
    off the TOOL, not the article)."""
    async with session_factory() as s:
        depts = {}
        for name in DEPTS:
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            depts[name] = d.id

        def _part(number, name, category):
            return Part(project_id=seed["project_id"], part_number=number, name=name,
                        part_type="internal_mfg", item_category=category,
                        created_by=seed["admin_id"])

        article = _part("ART-1", "Bracket", "article")
        tool = _part("1234", "Mold 1234", "tool")
        station = _part("1234-20", "In-cell station", "assembly_equipment")
        gauge = _part("1234-40", "Check gauge", "gauge")
        unrelated = _part("9999", "Someone else's tool", "tool")
        s.add_all([article, tool, station, gauge, unrelated])
        await s.flush()

        s.add_all([
            # tool produces the article
            PartRelation(from_part_id=tool.id, to_part_id=article.id,
                         relation_type="produces", created_by=seed["admin_id"]),
            # station and gauge serve the tool
            PartRelation(from_part_id=station.id, to_part_id=tool.id,
                         relation_type="serves", created_by=seed["admin_id"]),
            PartRelation(from_part_id=gauge.id, to_part_id=tool.id,
                         relation_type="serves", created_by=seed["admin_id"]),
        ])

        change = ChangeRequest(
            change_number="C-AO-1", title="objects", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        s.add(ChangeImpactedItem(change_id=change.id, part_id=article.id,
                                 is_lead=True, created_by=seed["admin_id"]))
        # routed: everyone except Quality, which stays unrouted
        for name in ("Tool Engineer", "Manufacturing Engineer", "APQP", "Development"):
            s.add(ChangeAssessment(change_id=change.id, department_id=depts[name],
                                   stage_order=1))
        await s.commit()
        return {"change_id": change.id, "depts": depts,
                "article": article.id, "tool": tool.id,
                "station": station.id, "gauge": gauge.id,
                "unrelated": unrelated.id}


async def _objects(client, auth, change_id):
    res = await client.get(f"/api/v1/changes/{change_id}/assessment-objects",
                           headers=auth)
    assert res.status_code == 200, res.text
    return {d["department_name"]: d for d in res.json()["departments"]}


async def test_objects_land_in_the_right_department(client, admin_auth, world):
    got = await _objects(client, admin_auth, world["change_id"])

    tools = got["Tool Engineer"]["objects"]
    assert [o["id"] for o in tools] == [world["tool"]]
    assert tools[0]["type"] == "tool"
    assert tools[0]["number"] == "1234"
    assert tools[0]["name"] == "Mold 1234"
    # reached through the impacted article, two hops away or one
    assert tools[0]["via_part_id"] == world["article"]

    equip = got["Manufacturing Engineer"]["objects"]
    assert [o["id"] for o in equip] == [world["station"]]
    assert equip[0]["type"] == "equipment"          # assembly_equipment renamed
    assert equip[0]["via_part_id"] == world["article"]

    gauges = got["APQP"]["objects"]
    assert [o["id"] for o in gauges] == [world["gauge"]]
    assert gauges[0]["type"] == "gauge"

    # Development assesses the impacted parts themselves
    dev = got["Development"]["objects"]
    assert [o["id"] for o in dev] == [world["article"]]
    assert dev[0]["type"] == "part"
    assert dev[0]["via_part_id"] == world["article"]

    # nothing unrelated leaked in
    all_ids = {o["id"] for d in got.values() for o in d["objects"]}
    assert world["unrelated"] not in all_ids


async def test_unrouted_department_is_absent(client, admin_auth, world):
    got = await _objects(client, admin_auth, world["change_id"])
    assert "Quality" not in got
    assert set(got) == {"Tool Engineer", "Manufacturing Engineer", "APQP",
                        "Development"}


async def test_department_outside_the_mapping_is_present_but_empty(
        client, admin_auth, world, session_factory):
    """Sales assesses too — it just has no objects of its own."""
    async with session_factory() as s:
        sales = Department(name="Sales", flow_type="action", is_active=True)
        s.add(sales)
        await s.flush()
        s.add(ChangeAssessment(change_id=world["change_id"],
                               department_id=sales.id, stage_order=2))
        await s.commit()

    got = await _objects(client, admin_auth, world["change_id"])
    assert "Sales" in got
    assert got["Sales"]["objects"] == []


async def test_no_impacted_items_means_empty_buckets(
        client, admin_auth, seed, session_factory):
    async with session_factory() as s:
        d = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(d)
        await s.flush()
        c = ChangeRequest(change_number="C-AO-2", title="bare", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], status="in_assessment")
        s.add(c)
        await s.flush()
        s.add(ChangeAssessment(change_id=c.id, department_id=d.id, stage_order=1))
        await s.commit()
        cid = c.id

    got = await _objects(client, admin_auth, cid)
    assert got["Tool Engineer"]["objects"] == []


async def test_no_cost_fields_are_exposed(client, admin_auth, world):
    """Cost belongs to the costing phase; these buckets are about scope."""
    res = await client.get(
        f"/api/v1/changes/{world['change_id']}/assessment-objects",
        headers=admin_auth)
    body = res.text.lower()
    for banned in ("cost", "price", "hour", "rate"):
        assert banned not in body, banned
