"""Project LOP: SEP items and SEP risk rows as referenced lines."""
import pytest
from sqlalchemy import select

from app.models.lop import LopLine
from app.models.sep import SepGate, SepItemAudit, SepWorkItem
from app.services.lop_departments import SEP_DEPARTMENT_MAP

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


@pytest.fixture(autouse=True)
def _forms(seed_forms):
    """The risk assessment form definition."""


@pytest.fixture
def lop_sep(client, lop_project, pm_auth, session_factory):
    """Activate SEP for the LOP project (all gates, 232 items)."""
    async def go():
        r = await client.post(f"/api/v1/sep/projects/{lop_project.id}/activate", headers=pm_auth)
        assert r.status_code == 201, r.text
        return r.json()
    return go


async def _gate(session_factory, pid, code="K0/RG1"):
    async with session_factory() as s:
        return (await s.execute(select(SepGate).where(
            SepGate.project_id == pid, SepGate.code == code))).scalar_one().id


async def _item(session_factory, gate_id, department=None, n=None):
    async with session_factory() as s:
        q = select(SepWorkItem).where(SepWorkItem.gate_id == gate_id, SepWorkItem.status == "open")
        if department:
            q = q.where(SepWorkItem.department == department)
        if n:
            q = q.where(SepWorkItem.item_no == n)
        return (await s.execute(q.order_by(SepWorkItem.item_no))).scalars().first().id


async def _open_lines(client, auth, pid):
    return (await client.get(f"{BASE}/projects/{pid}?view=open", headers=auth)).json()["lines"]


async def _set_target(client, auth, gate_id, day="2026-12-04"):
    r = await client.patch(f"/api/v1/sep/gates/{gate_id}", headers=auth,
                           json={"target_date": f"{day}T00:00:00"})
    assert r.status_code == 200, r.text


async def _from_sep(client, auth, pid, **body):
    return await client.post(f"{BASE}/projects/{pid}/lines/from-sep", headers=auth, json=body)


async def _item_state(session_factory, item_id):
    async with session_factory() as s:
        i = await s.get(SepWorkItem, item_id)
        return i.status, i.completed_at


async def _form_risk(client, auth, pid, **row):
    res = await client.get(f"/api/v1/forms/projects/{pid}", headers=auth)
    group = next(g for g in res.json() if g["key"] == "risk_assessment")
    if group["instances"]:
        inst = (await client.get(f"/api/v1/forms/instances/{group['instances'][0]['id']}", headers=auth)).json()
    else:
        inst = (await client.post(f"/api/v1/forms/projects/{pid}/instances",
                                  json={"key": "risk_assessment"}, headers=auth)).json()
    data = inst["data"]
    data["risks"] = list(data.get("risks") or []) + [
        {"gate": "K0/RG1", "risk": "Tool delay", "q": 0.1, "c": 0.1, "s": 0.1, "p": 0.5,
         "status": "open", **row}]
    res = await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _risk_rows(client, auth, pid):
    res = await client.get(f"/api/v1/forms/projects/{pid}", headers=auth)
    group = next(g for g in res.json() if g["key"] == "risk_assessment")
    inst = (await client.get(f"/api/v1/forms/instances/{group['instances'][-1]['id']}", headers=auth)).json()
    return inst["data"]["risks"]


async def test_department_map_is_the_agreed_one():
    assert SEP_DEPARTMENT_MAP["Development / Project Mgmt."] == "Project Manager"
    assert SEP_DEPARTMENT_MAP["(to be defined)"] is None
    assert SEP_DEPARTMENT_MAP["Industrial Enineering"] == "Manufacturing Engineer"


# ---------------------------------------------------------------- SEP items
async def test_no_sep_item_enters_by_itself(client, pm_auth, lop_project, lop_sep):
    await lop_sep()
    assert await _open_lines(client, pm_auth, lop_project.id) == []
    assert await _open_lines(client, pm_auth, lop_project.id) == []
    c = (await client.get(f"{BASE}/projects/{lop_project.id}/sep-candidates", headers=pm_auth)).json()
    assert c["gates"][0]["code"] == "K0/RG1" and len(c["gates"][0]["items"]) > 5
    assert {"id", "item_no", "title", "department"} <= set(c["gates"][0]["items"][0])


async def test_adding_one_item(client, pm_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    gate = await _gate(session_factory, lop_project.id)
    await _set_target(client, pm_auth, gate)
    item = await _item(session_factory, gate, "Advanced Product Quality Planning")
    r = await _from_sep(client, pm_auth, lop_project.id, item_id=item)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["kind"] == "sep_item" and b["department_name"] == "APQP"
    assert b["responsible_id"] == lop_project.quality_user_id and b["responsible_is_default"] is False
    assert b["due_date"] == "2026-12-04" and b["due_is_default"] is True
    assert b["source_label"].startswith("SEP K0/RG1") and b["text"]
    # idempotent: the same line again, not an error
    r2 = await _from_sep(client, pm_auth, lop_project.id, item_id=item)
    assert r2.status_code == 200 and r2.json()["id"] == b["id"]
    # an explicit date wins over the gate date
    other = await _item(session_factory, gate, "Sales")
    b2 = (await _from_sep(client, pm_auth, lop_project.id, item_id=other, due_date="2026-12-01")).json()
    assert b2["due_date"] == "2026-12-01" and b2["due_is_default"] is False
    # it left the candidates
    c = (await client.get(f"{BASE}/projects/{lop_project.id}/sep-candidates", headers=pm_auth)).json()
    ids = {i["id"] for g in c["gates"] for i in g["items"]}
    assert item not in ids and other not in ids


async def test_adding_a_gate_adds_its_open_items_with_defaults(
        client, pm_auth, lop_project, lop_sep, session_factory):
    from tests.conftest import make_department_member
    await make_department_member(session_factory, lop_project.outsider_id, "Production")  # no team slot
    await lop_sep()
    gate = await _gate(session_factory, lop_project.id)
    await _set_target(client, pm_auth, gate)
    async with session_factory() as s:
        n_open = len((await s.execute(select(SepWorkItem).where(
            SepWorkItem.gate_id == gate, SepWorkItem.status == "open"))).scalars().all())
    r = await _from_sep(client, pm_auth, lop_project.id, gate_id=gate, only_open=True)
    assert r.status_code == 201, r.text
    assert r.json()["added"] == n_open
    lines = await _open_lines(client, pm_auth, lop_project.id)
    assert len(lines) == n_open
    assert all(l["due_date"] == "2026-12-04" and l["due_is_default"] for l in lines)
    apqp = next(l for l in lines if l["department_name"] == "APQP")
    assert apqp["responsible_id"] == lop_project.quality_user_id
    # a department without a team member falls to the PM
    other = next(l for l in lines if l["department_name"] == "Production")
    assert other["responsible_id"] == lop_project.pm_id and other["responsible_is_default"]
    assert (await _from_sep(client, pm_auth, lop_project.id, gate_id=gate, only_open=True)).json()["added"] == 0


async def test_gate_without_date_gives_no_default_date(client, pm_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    gate = await _gate(session_factory, lop_project.id)
    b = (await _from_sep(client, pm_auth, lop_project.id, item_id=await _item(session_factory, gate))).json()
    assert b["due_date"] is None and b["due_is_default"] is False and b["under_control"] is False


async def test_unmapped_department_has_no_name(client, pm_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    gate = await _gate(session_factory, lop_project.id)
    async with session_factory() as s:
        item = (await s.execute(select(SepWorkItem).where(
            SepWorkItem.gate_id == gate, SepWorkItem.status == "open"))).scalars().first()
        item.department = "(to be defined)"
        await s.commit()
        item_id = item.id
    b = (await _from_sep(client, pm_auth, lop_project.id, item_id=item_id)).json()
    assert b["department_id"] is None and b["responsible_id"] is None


async def test_only_the_pm_adds_and_only_open_items(client, pm_auth, quality_auth, lop_project,
                                                    lop_sep, session_factory):
    await lop_sep()
    gate = await _gate(session_factory, lop_project.id)
    item = await _item(session_factory, gate)
    assert (await _from_sep(client, quality_auth, lop_project.id, item_id=item)).status_code == 403
    r = await client.patch(f"/api/v1/sep/items/{item}", headers=pm_auth, json={"status": "done"})
    assert r.status_code == 200
    assert (await _from_sep(client, pm_auth, lop_project.id, item_id=item)).status_code == 400
    assert (await _from_sep(client, pm_auth, lop_project.id)).status_code == 400


async def _one_line(client, pm_auth, lop_project, session_factory, **kw):
    gate = await _gate(session_factory, lop_project.id)
    item = await _item(session_factory, gate, **kw)
    line = (await _from_sep(client, pm_auth, lop_project.id, item_id=item)).json()
    return line["id"], item, gate


async def test_pm_closing_the_line_completes_the_sep_item(
        client, pm_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    line, item, _ = await _one_line(client, pm_auth, lop_project, session_factory)
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "closed"})
    assert r.status_code == 200 and r.json()["status"] == "closed"
    status, completed = await _item_state(session_factory, item)
    assert status == "done" and completed
    async with session_factory() as s:
        audits = (await s.execute(select(SepItemAudit).where(SepItemAudit.item_id == item))).scalars().all()
    assert [(a.field, a.old_value, a.new_value) for a in audits] == [("status", "open", "done")]
    assert await _open_lines(client, pm_auth, lop_project.id) == []


async def test_reopen_reopens_the_sep_item(client, pm_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    line, item, _ = await _one_line(client, pm_auth, lop_project, session_factory)
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "closed"})
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "open"})
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["reopened"] is True
    assert await _item_state(session_factory, item) == ("open", None)


async def test_non_pm_done_in_sep_view_becomes_done_check(
        client, pm_auth, quality_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    line, item, _ = await _one_line(client, pm_auth, lop_project, session_factory)
    r = await client.patch(f"/api/v1/sep/items/{item}", headers=quality_auth,
                           json={"status": "done", "remark": "finished"})
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "open" and b["lop_status"] == "done_check" and b["remark"] == "finished"
    lines = await _open_lines(client, pm_auth, lop_project.id)
    assert [(l["id"], l["status"]) for l in lines] == [(line, "done_check")]


async def test_sep_item_outside_lop_keeps_todays_behaviour(
        client, pm_auth, quality_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    gate = await _gate(session_factory, lop_project.id, "K/RG2")
    item = await _item(session_factory, gate)
    r = await client.patch(f"/api/v1/sep/items/{item}", headers=quality_auth, json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done" and "lop_status" not in r.json()


async def test_item_done_in_sep_by_pm_closes_the_line(
        client, pm_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    line, item, _ = await _one_line(client, pm_auth, lop_project, session_factory)
    r = await client.patch(f"/api/v1/sep/items/{item}", headers=pm_auth, json={"status": "not_applicable"})
    assert r.status_code == 200 and r.json()["lop_status"] == "closed"
    assert await _open_lines(client, pm_auth, lop_project.id) == []
    closed = (await client.get(f"{BASE}/projects/{lop_project.id}?view=closed", headers=pm_auth)).json()["lines"]
    assert closed[0]["id"] == line and closed[0]["closed_at"] and closed[0]["closed_by"] == lop_project.pm_id
    # item reopened in the SEP view: the line is open again
    await client.patch(f"/api/v1/sep/items/{item}", headers=pm_auth, json={"status": "open"})
    assert [l["id"] for l in await _open_lines(client, pm_auth, lop_project.id)] == [line]


async def test_gate_closed_shows_line_closed_and_edit_is_409_not_500(
        client, pm_auth, quality_auth, lop_project, lop_sep, session_factory):
    await lop_sep()
    line, item, gate = await _one_line(client, pm_auth, lop_project, session_factory)
    async with session_factory() as s:
        g = await s.get(SepGate, gate)
        g.status = "closed"
        await s.commit()
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "closed"})
    assert r.status_code == 409 and "gate is closed" in r.json()["detail"].lower()
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"title_x": 1, "next_check_date": "2026-12-01"})
    assert r.status_code == 409
    assert await _open_lines(client, pm_auth, lop_project.id) == []
    assert (await client.get(f"{BASE}/projects/{lop_project.id}?view=closed",
                             headers=pm_auth)).json()["lines"][0]["id"] == line
    assert (await _item_state(session_factory, item))[0] == "open"      # the item is untouched


# -------------------------------------------------------------------- risks
async def test_risk_with_countermeasure_and_due_becomes_a_line(client, pm_auth, lop_project):
    await _form_risk(client, pm_auth, lop_project.id, countermeasure="Order spare insert",
                     due="2026-11-30", responsible=lop_project.quality_user_id)
    await _form_risk(client, pm_auth, lop_project.id, risk="No plan")          # no countermeasure/due
    lines = await _open_lines(client, pm_auth, lop_project.id)
    assert len(lines) == 1
    b = lines[0]
    assert b["kind"] == "risk" and b["source_label"] == "SEP risk"
    assert b["text"] == "Order spare insert" and b["source_context"] == "Tool delay"
    assert b["due_date"] == "2026-11-30" and b["responsible_id"] == lop_project.quality_user_id
    assert b["responsible_is_default"] is False
    keys = [r.get("lop_key") for r in await _risk_rows(client, pm_auth, lop_project.id)]
    assert all(keys) and len(set(keys)) == 2 and b["ref_key"] == keys[0]


async def test_risk_responsible_outside_the_team_falls_to_the_pm(client, pm_auth, lop_project):
    await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30",
                     responsible=lop_project.outsider_id)
    b = (await _open_lines(client, pm_auth, lop_project.id))[0]
    assert b["responsible_id"] == lop_project.pm_id and b["responsible_is_default"] is True


async def test_closing_a_risk_line_sets_row_status_finished(client, pm_auth, lop_project):
    await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    line = (await _open_lines(client, pm_auth, lop_project.id))[0]["id"]
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "closed"})
    assert r.status_code == 200
    row = (await _risk_rows(client, pm_auth, lop_project.id))[0]
    assert row["status"] == "finished" and row["countermeasure"] == "Do it" and row["due"] == "2026-11-30"
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "open"})
    assert (await _risk_rows(client, pm_auth, lop_project.id))[0]["status"] == "started"


async def test_row_finished_in_the_form_closes_the_line(client, pm_auth, lop_project):
    inst = await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    await _open_lines(client, pm_auth, lop_project.id)
    data = (await client.get(f"/api/v1/forms/instances/{inst['id']}", headers=pm_auth)).json()["data"]
    data["risks"][0]["status"] = "finished"
    assert (await client.patch(f"/api/v1/forms/instances/{inst['id']}", headers=pm_auth,
                               json={"data": data})).status_code == 200
    assert await _open_lines(client, pm_auth, lop_project.id) == []


async def test_deleted_risk_row_drops_out_of_open_lines(client, pm_auth, lop_project, session_factory):
    inst = await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    assert len(await _open_lines(client, pm_auth, lop_project.id)) == 1
    data = (await client.get(f"/api/v1/forms/instances/{inst['id']}", headers=pm_auth)).json()["data"]
    data["risks"] = []
    assert (await client.patch(f"/api/v1/forms/instances/{inst['id']}", headers=pm_auth,
                               json={"data": data})).status_code == 200
    assert await _open_lines(client, pm_auth, lop_project.id) == []
    async with session_factory() as s:                      # the line itself is kept
        assert len((await s.execute(select(LopLine).where(LopLine.kind == "risk"))).scalars().all()) == 1


async def test_newer_risk_form_instance_keeps_lines_by_key(client, pm_auth, lop_project, session_factory):
    from app.models.forms import FormInstance
    inst = await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    line = (await _open_lines(client, pm_auth, lop_project.id))[0]
    async with session_factory() as s:
        old = await s.get(FormInstance, inst["id"])
        s.add(FormInstance(project_id=old.project_id, definition_id=old.definition_id, status="draft",
                           data={"header": {}, "risks": [dict(old.data["risks"][0], status="started")]},
                           owner_id=old.owner_id, created_by=old.created_by, updated_by=old.updated_by))
        await s.commit()
    lines = await _open_lines(client, pm_auth, lop_project.id)
    assert [l["id"] for l in lines] == [line["id"]]


async def test_sync_is_idempotent(client, pm_auth, lop_project, session_factory):
    await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    a = await _open_lines(client, pm_auth, lop_project.id)
    keys = [r["lop_key"] for r in await _risk_rows(client, pm_auth, lop_project.id)]
    b = await _open_lines(client, pm_auth, lop_project.id)
    assert [l["id"] for l in a] == [l["id"] for l in b]
    assert keys == [r["lop_key"] for r in await _risk_rows(client, pm_auth, lop_project.id)]
    from app.models.forms import FormEvent
    async with session_factory() as s:
        n = len((await s.execute(select(FormEvent))).scalars().all())
    await _open_lines(client, pm_auth, lop_project.id)
    async with session_factory() as s:
        assert len((await s.execute(select(FormEvent))).scalars().all()) == n     # no write


# ------------------------------------------------------------- fix round 1
async def _patch_form(client, auth, inst_id, risks):
    data = (await client.get(f"/api/v1/forms/instances/{inst_id}", headers=auth)).json()["data"]
    data["risks"] = risks
    return await client.patch(f"/api/v1/forms/instances/{inst_id}", headers=auth, json={"data": data})


async def test_submitted_risk_form_is_never_changed_by_the_lop(
        client, pm_auth, lop_project, session_factory):
    from app.models.forms import FormInstance
    inst = await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    line = (await _open_lines(client, pm_auth, lop_project.id))[0]["id"]      # row has its key
    async with session_factory() as s:
        i = await s.get(FormInstance, inst["id"])
        i.data = {**i.data, "risks": i.data["risks"] + [
            {"gate": "K0/RG1", "risk": "Second", "countermeasure": "Later", "due": "2026-12-01",
             "status": "open"}]}
        i.status = "submitted"
        await s.commit()
    lines = await _open_lines(client, pm_auth, lop_project.id)
    assert [l["id"] for l in lines] == [line]                 # keyless row waits for a reopen
    async with session_factory() as s:
        rows = (await s.get(FormInstance, inst["id"])).data["risks"]
    assert rows[0].get("lop_key") and not rows[1].get("lop_key")
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "closed"})
    assert r.status_code == 409
    assert r.json()["detail"] == "The risk form is submitted. Reopen it to change this line."
    assert [l["status"] for l in await _open_lines(client, pm_auth, lop_project.id)] == ["open"]


async def test_duplicate_create_returns_the_existing_line(
        client, pm_auth, lop_project, lop_sep, session_factory):
    from app.models.entities import User
    from app.services import lop_sources
    await lop_sep()
    gate = await _gate(session_factory, lop_project.id)
    item = await _item(session_factory, gate)
    first = (await _from_sep(client, pm_auth, lop_project.id, item_id=item)).json()["id"]
    async with session_factory() as s:                       # the second request lost the race
        user = await s.get(User, lop_project.pm_id)
        it = await s.get(SepWorkItem, item)
        g = await s.get(SepGate, gate)
        line, created = await lop_sources._new_sep_line(s, user, lop_project.id, it, g, None, {})
        assert created is False and line.id == first
        dup = LopLine(project_id=lop_project.id, kind="risk", ref_key="k1", status="open")
        s.add(dup)
        await s.commit()
    async with session_factory() as s:
        again = LopLine(project_id=lop_project.id, kind="risk", ref_key="k1", status="open")
        got, created = await lop_sources._insert_line(s, again)
        assert created is False and got.ref_key == "k1"
        await s.commit()
        n = (await s.execute(select(LopLine).where(LopLine.ref_key == "k1"))).scalars().all()
        assert len(n) == 1


async def test_stale_form_save_keeps_the_keys_and_lines(client, pm_auth, lop_project):
    inst = await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    stale = inst["data"]["risks"]                              # opened before the keys existed
    line = (await _open_lines(client, pm_auth, lop_project.id))[0]
    key = line["ref_key"]
    assert (await _patch_form(client, pm_auth, inst["id"], stale)).status_code == 200
    assert (await _risk_rows(client, pm_auth, lop_project.id))[0]["lop_key"] == key
    assert [l["id"] for l in await _open_lines(client, pm_auth, lop_project.id)] == [line["id"]]


async def test_genuinely_deleted_row_still_drops_its_line(client, pm_auth, lop_project):
    inst = await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    await _open_lines(client, pm_auth, lop_project.id)
    assert (await _patch_form(client, pm_auth, inst["id"], [])).status_code == 200
    assert await _open_lines(client, pm_auth, lop_project.id) == []


def test_reordered_or_edited_row_does_not_steal_a_key():
    from app.forms.risks import carry_over_lop_keys
    stored = {"risks": [{"risk": "A", "lop_key": "ka"}, {"risk": "B", "lop_key": "kb"}]}
    swapped = carry_over_lop_keys(stored, {"risks": [{"risk": "B"}, {"risk": "A"}]})
    assert [r.get("lop_key") for r in swapped["risks"]] == [None, None]
    edited = carry_over_lop_keys(stored, {"risks": [{"risk": "A edited"}, {"risk": "B"}]})
    assert [r.get("lop_key") for r in edited["risks"]] == [None, "kb"]
    used = carry_over_lop_keys(stored, {"risks": [{"risk": "A"}, {"risk": "B", "lop_key": "ka"}]})
    assert used["risks"][0].get("lop_key") is None


async def test_reader_opening_the_lop_writes_nothing_in_their_name(
        client, pm_auth, quality_auth, lop_project, session_factory):
    from app.models.forms import FormEvent
    await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    await _open_lines(client, quality_auth, lop_project.id)
    async with session_factory() as s:
        events = (await s.execute(select(FormEvent))).scalars().all()
        line = (await s.execute(select(LopLine).where(LopLine.kind == "risk"))).scalars().one()
    assert not [e for e in events if e.event == "saved" and e.user_id == lop_project.quality_user_id]
    keys = [e for e in events if e.event == "lop_keys"]
    assert len(keys) == 1 and keys[0].user_id == lop_project.pm_id
    assert line.created_by == lop_project.pm_id


async def test_mine_does_not_stamp_keys_or_create_lines(client, pm_auth, lop_project):
    await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    assert (await client.get(f"{BASE}/mine", headers=pm_auth)).status_code == 200
    assert not (await _risk_rows(client, pm_auth, lop_project.id))[0].get("lop_key")


async def test_risk_line_follows_the_row_due_date_until_the_pm_moves_it(client, pm_auth, lop_project):
    inst = await _form_risk(client, pm_auth, lop_project.id, countermeasure="Do it", due="2026-11-30")
    line = (await _open_lines(client, pm_auth, lop_project.id))[0]
    rows = (await _risk_rows(client, pm_auth, lop_project.id))
    rows[0]["due"] = "2026-12-05"
    assert (await _patch_form(client, pm_auth, inst["id"], rows)).status_code == 200
    b = (await _open_lines(client, pm_auth, lop_project.id))[0]
    assert b["due_date"] == b["first_due_date"] == "2026-12-05"
    h = (await client.get(f"{BASE}/lines/{line['id']}/history", headers=pm_auth)).json()
    assert any(e["type"] == "event" and e["field"] == "due_date" for e in h)
    r = await client.patch(f"{BASE}/lines/{line['id']}", headers=pm_auth,
                           json={"due_date": "2026-12-20", "reason": "supplier slipped"})
    assert r.status_code == 200
    rows[0]["due"] = "2026-12-08"
    assert (await _patch_form(client, pm_auth, inst["id"], rows)).status_code == 200
    assert (await _open_lines(client, pm_auth, lop_project.id))[0]["due_date"] == "2026-12-20"


async def test_other_integrity_errors_are_raised_not_swallowed(lop_project, session_factory):
    from sqlalchemy.exc import IntegrityError
    from app.services import lop_sources
    async with session_factory() as s:
        # NOT NULL violation on a column the model leaves required (no foreign keys needed)
        bad = LopLine(project_id=lop_project.id, kind=None, ref_key="bad1")
        with pytest.raises(IntegrityError):
            await lop_sources._insert_line(s, bad)
        await s.rollback()
    async with session_factory() as s:
        assert (await s.execute(select(LopLine).where(LopLine.ref_key == "bad1"))).first() is None
