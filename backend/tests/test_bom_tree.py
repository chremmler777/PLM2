"""BOM follows the revision; tree explosion and where-used."""
from datetime import date

from sqlalchemy import select

from app.models.part import PartBOMItem
from app.services.bom_tree_service import BomTreeService
from app.services.part_service import RevisionService


async def _mk_part(client, auth, seed, number, part_type="internal_mfg", with_e1=True):
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": number,
        "part_type": part_type, "data_classification": "confidential"}, headers=auth)
    assert res.status_code in (200, 201), res.text
    pid = res.json()["id"]
    rid = None
    if with_e1:
        r = await client.post(f"/api/v1/parts/{pid}/revisions/customer-data", headers=auth,
                              json={"statement": "review", "received_at": "2026-09-01"})
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
    return pid, rid


async def _add(client, auth, pid, rid, child_id=None, name=None, qty=1):
    body = {"quantity": qty, "unit": "pcs"}
    if child_id:
        body["child_part_id"] = child_id
    else:
        body["name"] = name
    r = await client.post(f"/api/v1/parts/{pid}/revisions/{rid}/bom", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _lines(session_factory, revision_id):
    async with session_factory() as s:
        rows = (await s.execute(select(PartBOMItem).where(PartBOMItem.revision_id == revision_id)
                                .order_by(PartBOMItem.position))).scalars().all()
        return [(r.item_number, r.child_part_id, r.name, r.quantity, r.unit) for r in rows]


async def test_bom_copies_forward_to_new_major_proposal_and_promotion(client, eng_auth, seed, session_factory):
    top, e1 = await _mk_part(client, eng_auth, seed, "TOP")
    bolt, _ = await _mk_part(client, eng_auth, seed, "BOLT", "purchased", with_e1=False)
    await _add(client, eng_auth, top, e1, child_id=bolt, qty=4)
    await _add(client, eng_auth, top, e1, name="Glue", qty=0.5)
    e1_lines = await _lines(session_factory, e1)

    # new customer major copies from the previous major
    e2 = (await client.post(f"/api/v1/parts/{top}/revisions/customer-data", headers=eng_auth,
                            json={"statement": "review", "received_at": "2026-09-02"})).json()
    assert await _lines(session_factory, e2["id"]) == e1_lines

    # proposal copies from its parent, and edits there do not touch the parent
    p = (await client.post(f"/api/v1/parts/{top}/revisions/proposals", headers=eng_auth,
                           json={"parent_revision_id": e2["id"]})).json()
    assert await _lines(session_factory, p["id"]) == e1_lines
    await _add(client, eng_auth, top, p["id"], name="Clip", qty=2)
    assert len(await _lines(session_factory, p["id"])) == 3
    assert len(await _lines(session_factory, e2["id"])) == 2

    # promotion carries the proposal's lines, not the old major's
    one = (await client.post(f"/api/v1/parts/{top}/revisions/{p['id']}/promote", headers=eng_auth,
                             json={"statement": "official", "received_at": "2026-09-03"})).json()
    assert one["revision_name"] == "1"
    assert [l[2] for l in await _lines(session_factory, one["id"])] == ["BOLT", "Glue", "Clip"]


async def test_tree_multiplies_quantities_and_where_used(client, eng_auth, seed):
    top, top_rev = await _mk_part(client, eng_auth, seed, "TOP")
    sub, sub_rev = await _mk_part(client, eng_auth, seed, "SUB")
    bolt, _ = await _mk_part(client, eng_auth, seed, "BOLT", "purchased", with_e1=False)
    await _add(client, eng_auth, top, top_rev, child_id=sub, qty=2)
    await _add(client, eng_auth, top, top_rev, child_id=bolt, qty=1)
    await _add(client, eng_auth, sub, sub_rev, child_id=bolt, qty=3)

    r = await client.get(f"/api/v1/parts/{top}/bom-tree", headers=eng_auth)
    assert r.status_code == 200, r.text
    tree = r.json()
    assert tree["part_number"] == "TOP" and tree["revision_name"] == "E1"
    sub_line = next(l for l in tree["lines"] if l["child"] and l["child"]["part_number"] == "SUB")
    assert sub_line["quantity"] == 2 and sub_line["total_quantity"] == 2
    bolt_in_sub = sub_line["child"]["lines"][0]
    assert bolt_in_sub["quantity"] == 3 and bolt_in_sub["total_quantity"] == 6
    assert bolt_in_sub["child"]["revision_name"] is None  # no customer data yet
    assert bolt_in_sub["child"]["part_type"] == "purchased"

    r = await client.get(f"/api/v1/parts/{bolt}/where-used", headers=eng_auth)
    assert r.status_code == 200, r.text
    used = r.json()
    assert sorted(u["part_number"] for u in used) == ["SUB", "TOP"]
    assert next(u for u in used if u["part_number"] == "SUB")["parents"][0]["part_number"] == "TOP"


async def test_tree_stops_on_cycle(client, eng_auth, seed, session_factory):
    a, a_rev = await _mk_part(client, eng_auth, seed, "A")
    b, b_rev = await _mk_part(client, eng_auth, seed, "B")
    await _add(client, eng_auth, a, a_rev, child_id=b)
    await _add(client, eng_auth, b, b_rev, child_id=a)
    async with session_factory() as s:
        tree = await BomTreeService.tree(s, a)
    b_node = tree["lines"][0]["child"]
    assert b_node["part_number"] == "B"
    assert b_node["lines"][0]["child"]["cycle"] is True
    assert b_node["lines"][0]["child"]["lines"] == []


async def test_tree_uses_a_given_revision(client, eng_auth, seed, session_factory):
    top, e1 = await _mk_part(client, eng_auth, seed, "TOP")
    bolt, _ = await _mk_part(client, eng_auth, seed, "BOLT", "purchased", with_e1=False)
    await _add(client, eng_auth, top, e1, child_id=bolt, qty=1)
    async with session_factory() as s:
        e2 = await RevisionService.receive_customer_data(s, top, "review", date(2026, 9, 2), created_by=seed["admin_id"])
        await s.commit()
        e2_id = e2.id
    r = await client.get(f"/api/v1/parts/{top}/bom-tree", params={"revision_id": e1}, headers=eng_auth)
    assert r.json()["revision_id"] == e1
    r = await client.get(f"/api/v1/parts/{top}/bom-tree", headers=eng_auth)
    assert r.json()["revision_id"] == e2_id  # active = newest customer major
