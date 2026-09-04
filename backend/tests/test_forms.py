"""SEP forms engine: definitions, instances, events, SEP item linking."""
from sqlalchemy import select

from app.models.forms import FormDefinition, FormInstance, FormEvent


async def test_models_roundtrip(session_factory, seed):
    async with session_factory() as s:
        d = FormDefinition(key="t", version=1, title="T", implements=None, cardinality="single",
                           gate_items=False, body={"sections": []})
        s.add(d)
        await s.flush()
        inst = FormInstance(project_id=seed["project_id"], definition_id=d.id, status="draft",
                            data={"a": 1}, created_by=seed["admin_id"], updated_by=seed["admin_id"])
        s.add(inst)
        await s.flush()
        s.add(FormEvent(instance_id=inst.id, user_id=seed["admin_id"], event="created"))
        await s.commit()
    async with session_factory() as s:
        got = (await s.execute(select(FormInstance))).scalar_one()
        assert got.data == {"a": 1}
        ev = (await s.execute(select(FormEvent))).scalar_one()
        assert ev.event == "created" and ev.role is None


import pytest
from datetime import datetime

from app.forms.loader import load_definitions
from app.forms.service import (
    create_instance, save_instance, submit_instance, reopen_instance, sign_instance,
    signatures_state, FormError,
)
from app.models import User
from app.models.sep import SepWorkItem, SepItemAudit, SepGate


async def _user(session_factory, uid):
    async with session_factory() as s:
        return await s.get(User, uid)


async def _activate_sep(client, auth, project_id):
    res = await client.post(f"/api/v1/sep/projects/{project_id}/activate", headers=auth)
    assert res.status_code == 201, res.text


async def test_create_prefills_and_enforces_single(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s)
        await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "risk_assessment", user)
        await s.commit()
        assert inst.status == "draft"
        assert inst.data["header"]["project_no"] == "proj"
        assert inst.data["header"]["project_manager"] == seed["engineer_id"]
        assert len(inst.data["header"]["date"]) == 10
        with pytest.raises(FormError) as ei:
            await create_instance(s, seed["project_id"], "risk_assessment", user)
        assert ei.value.status == 409
        with pytest.raises(FormError) as ei:
            await create_instance(s, seed["project_id"], "nope", user)
        assert ei.value.status == 404
        # multi cardinality allows a second instance
        await create_instance(s, seed["project_id"], "deviation_agreement", user)
        await create_instance(s, seed["project_id"], "deviation_agreement", user)
        await s.commit()


async def test_contact_list_prefills_team_from_sep_responsibles(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s)
        item = (await s.execute(select(SepWorkItem).where(SepWorkItem.project_id == seed["project_id"]).limit(1))).scalar_one()
        item.responsible_id = seed["admin_id"]
        await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "contact_list", user)
        assert [r["name"] for r in inst.data["contacts"]] == ["Admin"]
        assert inst.data["contacts"][0]["email"] == "admin@test.io"


async def test_save_recomputes_and_records_diff(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s); await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "risk_assessment", user)
        data = dict(inst.data)
        data["risks"] = [{"gate": "K0/RG1", "risk": "Late tooling", "q": 0.5, "c": 0.5, "s": 1, "p": 1, "status": "open"}]
        inst = await save_instance(s, inst, data, user)
        await s.commit()
        assert inst.data["risks"][0]["rkz"] == pytest.approx(2.0)
        assert inst.data["risks"][0]["priority"] == "very_high"
        assert inst.data["risks_footer"]["Open"] == 1
        ev = [e for e in inst.events if e.event == "saved"][-1]
        assert "risks" in ev.diff


async def test_submit_flips_linked_items_and_reopen_restores(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s); await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "project_legitimization", user)
        with pytest.raises(FormError) as ei:
            await submit_instance(s, inst, user)
        assert ei.value.status == 422 and "budget" in ei.value.extra["missing"]
        data = dict(inst.data)
        data["header"]["project_title"] = "P"
        data["budget"] = [{"item": "Tooling", "budget": 1000}]
        inst = await save_instance(s, inst, data, user)
        # one linked item is not_applicable: must stay untouched
        na_item = (await s.execute(select(SepWorkItem).join(SepGate).where(
            SepWorkItem.project_id == seed["project_id"], SepGate.code == "K/RG2", SepWorkItem.item_no == 7))).scalar_one()
        na_item.status = "not_applicable"
        await s.flush()
        inst = await submit_instance(s, inst, user)
        await s.commit()
        assert inst.status == "submitted" and inst.submitted_by == user.id
        k0 = (await s.execute(select(SepWorkItem).join(SepGate).where(
            SepWorkItem.project_id == seed["project_id"], SepGate.code == "K0/RG1", SepWorkItem.item_no == 39))).scalar_one()
        assert k0.status == "done" and k0.remark == "via form Project Legitimization"
        await s.refresh(na_item)
        assert na_item.status == "not_applicable"
        audits = (await s.execute(select(SepItemAudit).where(SepItemAudit.item_id == k0.id))).scalars().all()
        assert audits[-1].new_value == "done" and audits[-1].user_id == user.id
        # saving a submitted form is refused
        with pytest.raises(FormError) as ei:
            await save_instance(s, inst, data, user)
        assert ei.value.status == 409
        inst = await reopen_instance(s, inst, user)
        await s.commit()
        await s.refresh(k0)
        assert inst.status == "reopened" and k0.status == "open"


async def test_submit_does_not_touch_closed_gate_items(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s)
        gate = (await s.execute(select(SepGate).where(SepGate.project_id == seed["project_id"], SepGate.code == "K0/RG1"))).scalar_one()
        gate.status = "closed"
        await s.commit()
    user = await _user(session_factory, seed["engineer_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "risk_assessment", user)
        inst = await submit_instance(s, inst, user)
        await s.commit()
        k0 = (await s.execute(select(SepWorkItem).join(SepGate).where(
            SepWorkItem.project_id == seed["project_id"], SepGate.code == "K0/RG1", SepWorkItem.item_no == 2))).scalar_one()
        assert k0.status == "open"


async def test_signatures_four_eyes(session_factory, seed, client, eng_auth):
    await _activate_sep(client, eng_auth, seed["project_id"])
    async with session_factory() as s:
        await load_definitions(s); await s.commit()
    eng = await _user(session_factory, seed["engineer_id"])
    adm = await _user(session_factory, seed["admin_id"])
    async with session_factory() as s:
        inst = await create_instance(s, seed["project_id"], "project_legitimization", eng)
        data = dict(inst.data); data["header"]["project_title"] = "P"; data["budget"] = [{"item": "Tooling", "budget": 1}]
        inst = await save_instance(s, inst, data, eng)
        inst = await submit_instance(s, inst, eng)
        with pytest.raises(FormError):
            await sign_instance(s, inst, "quality", eng)  # role not in definition
        inst = await sign_instance(s, inst, "pm", eng)
        with pytest.raises(FormError):
            await sign_instance(s, inst, "md", eng)  # same user, second role
        with pytest.raises(FormError):
            await sign_instance(s, inst, "pm", adm)  # already signed
        inst = await sign_instance(s, inst, "md", adm)
        await s.commit()
        state = signatures_state(inst)
        assert state["pm"]["user_id"] == eng.id and state["md"]["user_id"] == adm.id
        # reopen invalidates signatures
        inst = await reopen_instance(s, inst, eng)
        assert signatures_state(inst) == {"md": None, "pm": None}


async def _seed_defs(session_factory):
    async with session_factory() as s:
        await load_definitions(s); await s.commit()


async def test_api_lifecycle(client, eng_auth, admin_auth, seed, session_factory):
    await _activate_sep(client, eng_auth, seed["project_id"])
    await _seed_defs(session_factory)
    res = await client.get("/api/v1/forms/definitions", headers=eng_auth)
    assert res.status_code == 200 and {d["key"] for d in res.json()} >= {"risk_assessment", "lop"}

    res = await client.post(f"/api/v1/forms/projects/{seed['project_id']}/instances", json={"key": "project_legitimization"}, headers=eng_auth)
    assert res.status_code == 201, res.text
    inst = res.json()
    assert inst["status"] == "draft" and inst["data"]["header"]["project_no"] == "proj"
    res = await client.post(f"/api/v1/forms/projects/{seed['project_id']}/instances", json={"key": "project_legitimization"}, headers=eng_auth)
    assert res.status_code == 409

    res = await client.get(f"/api/v1/forms/instances/{inst['id']}", headers=eng_auth)
    assert res.status_code == 200 and res.json()["definition"]["key"] == "project_legitimization"
    assert [e["event"] for e in res.json()["events"]] == ["created"]

    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/submit", headers=eng_auth)
    assert res.status_code == 422 and "budget" in res.json()["detail"]["missing"]

    data = inst["data"]; data["header"]["project_title"] = "P"; data["budget"] = [{"item": "Tooling", "budget": 5}]
    res = await client.patch(f"/api/v1/forms/instances/{inst['id']}", json={"data": data}, headers=eng_auth)
    assert res.status_code == 200 and res.json()["data"]["budget_footer"]["Total budget"] == 5

    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/submit", headers=eng_auth)
    assert res.status_code == 200 and res.json()["status"] == "submitted"
    assert res.json()["signatures"] == {"md": None, "pm": None}

    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/sign", json={"role": "pm"}, headers=eng_auth)
    assert res.status_code == 200 and res.json()["signatures"]["pm"]["user_name"] == "Engineer"
    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/sign", json={"role": "md"}, headers=eng_auth)
    assert res.status_code == 409
    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/sign", json={"role": "md"}, headers=admin_auth)
    assert res.status_code == 200

    # SEP payload shows the form on its items
    sep = (await client.get(f"/api/v1/sep/projects/{seed['project_id']}", headers=eng_auth)).json()
    k0 = next(g for g in sep["gates"] if g["code"] == "K0/RG1")
    item39 = next(i for i in k0["items"] if i["item_no"] == 39)
    assert item39["form"] == {"key": "project_legitimization", "title": "Project Legitimization",
                              "instance_id": inst["id"], "status": "submitted"}
    assert item39["status"] == "done"
    item2 = next(i for i in k0["items"] if i["item_no"] == 2)
    assert item2["form"]["key"] == "risk_assessment" and item2["form"]["instance_id"] is None

    res = await client.post(f"/api/v1/forms/instances/{inst['id']}/reopen", headers=admin_auth)
    assert res.status_code == 200 and res.json()["status"] == "reopened"

    res = await client.get(f"/api/v1/forms/projects/{seed['project_id']}", headers=eng_auth)
    assert res.status_code == 200
    groups = {g["key"]: g for g in res.json()}
    assert groups["project_legitimization"]["instances"][0]["status"] == "reopened"
    assert groups["lop"]["instances"] == [] and groups["lop"]["cardinality"] == "single"


async def test_my_forms(client, eng_auth, admin_auth, seed, session_factory):
    await _activate_sep(client, eng_auth, seed["project_id"])
    await _seed_defs(session_factory)
    res = await client.post(f"/api/v1/forms/projects/{seed['project_id']}/instances", json={"key": "lop"}, headers=eng_auth)
    assert res.status_code == 201
    mine = (await client.get("/api/v1/forms/my-forms", headers=eng_auth)).json()
    assert [m["key"] for m in mine] == ["lop"] and mine[0]["reason"] == "draft"
    assert (await client.get("/api/v1/forms/my-forms", headers=admin_auth)).json() == []


async def test_sep_references_on_items(client, eng_auth, seed):
    await _activate_sep(client, eng_auth, seed["project_id"])
    sep = (await client.get(f"/api/v1/sep/projects/{seed['project_id']}", headers=eng_auth)).json()
    k2 = next(g for g in sep["gates"] if g["code"] == "K/RG2")
    item10 = next(i for i in k2["items"] if i["item_no"] == 10)
    assert any(r["title"].startswith("Process description") for r in item10["references"])
