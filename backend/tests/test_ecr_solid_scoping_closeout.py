"""Close-out, area 2 intake + scoping: negative tests.

Each test names the issue it pins (A2-xx)."""
import pytest
from sqlalchemy import select

from tests.conftest import lock_impact, to_scoping
from tests.test_ecr_solid_ppap_flip import (
    _user, _responsible, _internal_in_scoping, _proceed, _ppap)

pytestmark = pytest.mark.asyncio


async def _starters(session_factory, *names):
    """Flag departments can_start_change (else everyone may start one)."""
    from app.models.workflow import Department
    from tests.conftest import make_department_member  # noqa: F401
    async with session_factory() as s:
        for n in names:
            d = (await s.execute(select(Department).where(
                Department.name == n))).scalar_one_or_none()
            if d is None:
                d = Department(name=n, flow_type="action", is_active=True)
                s.add(d)
            d.can_start_change = True
        await s.commit()


async def _set(session_factory, cid, **fields):
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        for k, v in fields.items():
            setattr(c, k, v)
        await s.commit()


async def _get(session_factory, cid):
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        return await s.get(ChangeRequest, cid)


# ---- A2-01: the room's cost carrier follows the PATCH flip rules ----------

async def test_a2_01_engineer_lead_cannot_make_the_room_carrier_customer(
        client, admin_auth, seed, session_factory):
    cid, _ = await _internal_in_scoping(client, admin_auth, seed, "a201")
    eng_id, dev_id, eng = await _user(client, session_factory, seed, "e201", "Development")
    sally, sales_id, _ = await _user(client, session_factory, seed, "s201", "Sales")
    pm_uid, pm_id, pm = await _user(client, session_factory, seed, "p201", "Project Manager")
    await _starters(session_factory, "Sales", "Project Manager")
    await _responsible(session_factory, seed, sales_id, sally)
    await _responsible(session_factory, seed, pm_id, pm_uid)
    await _set(session_factory, cid, lead_id=eng_id, raised_by=eng_id)
    body = {"channel": "meeting", "participants": [{"name": "Eva"}],
            "department_rasic": {str(dev_id): "R"}}
    url = f"/api/v1/changes/{cid}/meetings"
    # negative: the engineering lead may not make it a customer change here
    res = await client.post(url, json={**body, "cost_carrier": "customer"}, headers=eng)
    assert res.status_code == 403, res.text
    assert "customer change" in res.json()["detail"]
    res = await client.post(url, json={**body, "cost_carrier": "internal"}, headers=eng)
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    res = await client.patch(f"{url}/{mid}", json={"cost_carrier": "customer"}, headers=eng)
    assert res.status_code == 403, res.text
    # Project Management may; proceed applies the C10 / [R4] people
    res = await client.patch(f"{url}/{mid}", json={"cost_carrier": "customer"}, headers=pm)
    assert res.status_code == 200, res.text
    await lock_impact(session_factory, cid)
    res = await _proceed(client, pm, cid, mid)
    assert res.status_code == 200, res.text
    c = await _get(session_factory, cid)
    assert c.customer_relevant is True and c.status == "in_assessment"
    assert c.sales_owner_id == sally and c.lead_id == pm_uid


async def test_a2_01_room_carrier_internal_drops_the_sales_owner(
        client, admin_auth, seed, session_factory):
    sally, sales_id, _ = await _user(client, session_factory, seed, "s202", "Sales")
    eng_id, dev_id, eng = await _user(client, session_factory, seed, "e202", "Development")
    _, qid, quality = await _user(client, session_factory, seed, "q202", "Quality")
    await _starters(session_factory, "Sales", "Project Manager")
    await _responsible(session_factory, seed, sales_id, sally)
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "a2-01 back", "reason": "r",
        "change_type": "physical_part", "customer_relevant": True,
        "lead_id": seed["admin_id"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": "ART-A202",
        "name": "Part", "part_type": "internal_mfg"}, headers=admin_auth)
    r = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                          json={"part_id": part.json()["id"], "is_lead": True},
                          headers=admin_auth)
    assert r.status_code == 200, r.text
    await to_scoping(client, admin_auth, cid)
    assert (await _get(session_factory, cid)).sales_owner_id == sally
    body = {"channel": "meeting", "participants": [{"name": "Eva"}],
            "department_rasic": {str(qid): "R"}}
    url = f"/api/v1/changes/{cid}/meetings"
    # negative: an engineering lead may not take the customer off either
    await _set(session_factory, cid, lead_id=eng_id)
    res = await client.post(url, json={**body, "cost_carrier": "internal"}, headers=eng)
    assert res.status_code == 403, res.text
    await _set(session_factory, cid, lead_id=seed["admin_id"])
    res = await client.post(url, json={**body, "cost_carrier": "internal"},
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    res = await _ppap(client, quality, cid, answer="no", basis="control_plan",
                      ref="CP-4711 rev 3")
    assert res.status_code == 200, res.text
    await lock_impact(session_factory, cid)
    res = await _proceed(client, admin_auth, cid, mid)
    assert res.status_code == 200, res.text
    c = await _get(session_factory, cid)
    assert c.customer_relevant is False and c.sales_owner_id is None


# ---- A2-02: a scoping question is answered Confirmed or Assumed -----------

async def test_a2_02_scoping_question_refuses_a_bare_ok(
        client, admin_auth, seed, session_factory):
    from tests.test_ecr_solid_scoping_v2 import (
        _scoping, _user as _sv_user, _question, _raise)
    cid, _ = await _scoping(client, admin_auth, seed, "a202")
    _, proc, pe = await _sv_user(client, session_factory, seed, "pe202", "Process Engineer")
    _, _, sales = await _sv_user(client, session_factory, seed, "sa202", "Sales")
    q = (await _raise(client, pe, cid, _question(proc))).json()
    url = f"/api/v1/changes/{cid}/concerns/{q['id']}/answer"
    # negative: a typed scoping question takes no free 'ok'
    res = await client.post(url, json={"note": "ok"}, headers=sales)
    assert res.status_code == 400, res.text
    assert "Confirmed" in res.json()["detail"]
    # a legacy (untyped) needs_info question in scoping neither
    from app.models.change import ChangeConcern
    async with session_factory() as s:
        legacy = ChangeConcern(change_id=cid, raised_by=seed["admin_id"],
                               kind="needs_info", note="Legacy: which grain?")
        s.add(legacy)
        await s.commit()
        lid = legacy.id
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{lid}/answer",
                            json={"note": "ok"}, headers=admin_auth)
    assert res.status_code == 400, res.text
    # the answer form passes
    res = await client.post(url, json={
        "answer_kind": "assumed", "assumed_value": "90000", "assumed_unit": "pcs/yr",
        "assumed_risk": "tool too small"}, headers=sales)
    assert res.status_code == 200, res.text


async def test_a2_02_switch_off_keeps_the_free_answer(
        client, admin_auth, seed, session_factory, monkeypatch):
    from tests.test_ecr_solid_scoping_v2 import _scoping
    from app.services import cm_switches
    from app.models.change import ChangeConcern
    cid, _ = await _scoping(client, admin_auth, seed, "a202off")
    async with session_factory() as s:
        legacy = ChangeConcern(change_id=cid, raised_by=seed["admin_id"],
                               kind="needs_info", note="Which grain?")
        s.add(legacy)
        await s.commit()
        lid = legacy.id
    monkeypatch.setattr(cm_switches, "SCOPING_V2", False)
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{lid}/answer",
                            json={"note": "Grain K31 per mail 12 Oct"}, headers=admin_auth)
    assert res.status_code == 200, res.text
