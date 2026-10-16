"""ECR-solid C16 (spec §4 "Impact edits after the lock", switch
ASSESSMENT_V2): after proceed and before the offer, the run team changes the
impacted set only with a reason; the departments whose objects moved get
their finalized costing back (in quoting the change steps back to costing)
and are told once. Others may not edit at all (P1-5, kept)."""
import json
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeImpactedItem, ChangeRequest
from app.models.notification import Notification
from app.models.part import Part
from app.services import cm_switches
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def locked(client, session_factory, seed):
    """In costing, Development routed and finalized on part A."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="li-dev", email="li-dev@test.io",
                 full_name="LI dev", hashed_password=get_password_hash("li-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        dev_user = u.id
    dev = await make_department_member(session_factory, dev_user, "Development")
    async with session_factory() as s:
        a = Part(project_id=seed["project_id"], part_number="ART-LI-A", name="A",
                 part_type="internal_mfg", created_by=seed["admin_id"])
        b = Part(project_id=seed["project_id"], part_number="ART-LI-B", name="B",
                 part_type="internal_mfg", created_by=seed["admin_id"])
        s.add_all([a, b])
        await s.flush()
        change = ChangeRequest(
            change_number="C-LI-1", title="locked edit", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="costing",
            customer_relevant=True, impact_confirmed_at=datetime.utcnow(),
            impact_confirmed_by=seed["admin_id"])
        s.add(change)
        await s.flush()
        s.add(ChangeImpactedItem(change_id=change.id, part_id=a.id, is_lead=True,
                                 created_by=seed["admin_id"]))
        s.add(ChangeAssessment(
            change_id=change.id, department_id=dev, stage_order=1, rasic_letter="R",
            status="submitted", verdict="feasible", submitted_at=datetime(2026, 9, 1),
            owner_id=dev_user,
            details=json.dumps({"impacts": [{"key": "x", "answer": "yes", "impacted": True}],
                                "costing_finalized_at": "2026-10-01T00:00:00"})))
        await s.commit()
        return {"cid": change.id, "a": a.id, "b": b.id, "dev": dev,
                "dev_user": dev_user, "dev_auth": await login(client, "li-dev@test.io")}


def _u(x, tail=""):
    return f"/api/v1/changes/{x['cid']}{tail}"


async def test_an_edit_after_the_lock_needs_a_reason_and_reopens_costing(
        client, admin_auth, locked, session_factory):
    res = await client.post(_u(locked, "/impacted-items"),
                            json={"part_id": locked["b"]}, headers=admin_auth)
    assert res.status_code == 400 and "say why it changes" in res.json()["detail"]
    res = await client.post(_u(locked, "/impacted-items"),
                            json={"part_id": locked["b"], "reason": "ok"},
                            headers=admin_auth)
    assert res.status_code == 400
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    detail = (await client.get(_u(locked), headers=admin_auth)).json()
    assert detail["costing_finalized_department_ids"] == []
    assert locked["dev"] in detail["costing_pending_department_ids"]
    async with session_factory() as s:
        told = (await s.execute(select(Notification).where(
            Notification.kind == "impact_edited"))).scalars().all()
        assert [n.user_id for n in told] == [locked["dev_user"]]
        assert "ART-LI-B" in told[0].body and "costing is open again" in told[0].body
        # R5/R37: a submitted answer is not reopened: in costing the notice
        # names the exits that exist (the reopened costing, the lead by
        # name), never a bare "Check your answer" nor a send-back that
        # does not exist
        body = told[0].body
        assert "correct your costing" in body and "tell " in body
        assert "send" not in body and "Check your answer" not in body


async def test_a_department_member_may_not_edit_after_the_lock(client, locked):
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=locked["dev_auth"])
    assert res.status_code == 403


async def test_in_quoting_the_change_steps_back_to_costing(
        client, admin_auth, locked, session_factory):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, locked["cid"])
        c.status = "quoting"
        await s.commit()
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, locked["cid"])).status == "costing"


async def test_switch_off_keeps_the_silent_edit(client, admin_auth, locked, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    res = await client.post(_u(locked, "/impacted-items"),
                            json={"part_id": locked["b"]}, headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_in_assessment_the_notice_names_the_risk_and_it_works(
        client, admin_auth, locked, session_factory):
    """R5 (review L5 loop 2): the exit the notice names is one the
    department can take: a risk on its own submitted assessment (an answer
    of impact no: impact yes is sent back, A3-06)."""
    async with session_factory() as s:
        c = await s.get(ChangeRequest, locked["cid"])
        c.status = "in_assessment"
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        a.details = json.dumps({"impacts": [{"key": "x", "answer": "no", "impacted": False}]})
        await s.commit()
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        body = (await s.execute(select(Notification.body).where(
            Notification.kind == "impact_edited"))).scalars().one()
    assert "record it as a risk on your assessment" in body
    res = await client.post(_u(locked, "/concerns"), json={
        "kind": "risk", "risk_type": "dimensional_issue", "severity": 2,
        "note": "Mirror part B needs its own insert", "department_id": locked["dev"]},
        headers=locked["dev_auth"])
    assert res.status_code == 200, res.text


async def test_the_relation_seed_is_an_impact_edit_too(
        client, admin_auth, locked, session_factory, seed):
    """A3-03: seeding related parts past the lock is no second road around
    C16: no reason, 400; with a reason the costing reopens as for any edit."""
    from app.models.part import PartRelation
    async with session_factory() as s:
        c = await s.get(ChangeRequest, locked["cid"])
        c.status = "in_assessment"
        s.add(PartRelation(from_part_id=locked["b"], to_part_id=locked["a"],
                           relation_type="produces", created_by=seed["admin_id"]))
        await s.commit()
    res = await client.post(_u(locked, "/impacted-items/seed"), headers=admin_auth)
    assert res.status_code == 400 and "say why it changes" in res.json()["detail"]
    async with session_factory() as s:
        n = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == locked["cid"]))).scalars().all()
        assert len(n) == 1                                   # nothing added
    res = await client.post(_u(locked, "/impacted-items/seed"),
                            params={"reason": "Tool B produces A, it is affected"},
                            headers=admin_auth)
    assert res.status_code == 200 and res.json()["added"] == 1, res.text
    detail = (await client.get(_u(locked), headers=admin_auth)).json()
    assert detail["costing_finalized_department_ids"] == []


async def test_in_assessment_an_impact_yes_answer_is_sent_back(
        client, admin_auth, locked, session_factory):
    """A3-06 (spec §4 minimal C16 'technical impact yes reopens
    assessment'): the department whose objects moved and whose submitted
    answer said impact yes gets its assessment back, with the reason."""
    async with session_factory() as s:
        c = await s.get(ChangeRequest, locked["cid"])
        c.status = "in_assessment"
        await s.commit()
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        assert a.submitted_at is None and a.verdict == "pending"
        assert a.details_dict["impacts"][0]["impacted"] is True     # answer kept
        body = (await s.execute(select(Notification.body).where(
            Notification.kind == "impact_edited"))).scalars().one()
        assert "Your assessment is open again" in body
        assert "Customer added the mirror part B" in body
        from app.models.change import ChangeChangelog
        log = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == locked["cid"],
            ChangeChangelog.action == "assessment_sent_back"))).scalars().one()
        assert "mirror part B" in log.notes
    # the department answers again
    from tests.checklist_helpers import answered
    res = await client.post(_u(locked, "/assessments"), json={
        "department_id": locked["dev"], "verdict": "feasible",
        "details": {"impacts": answered("Development")}},
        headers=locked["dev_auth"])
    assert res.status_code == 200, res.text


async def test_switch_off_or_costing_sends_nothing_back(
        client, admin_auth, locked, session_factory, monkeypatch):
    """A3-06 negative: in costing the submitted answer stays (the engine has
    moved on: costing reopens, the notice names the lead); switch off too."""
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        assert a.submitted_at is not None and a.verdict == "feasible"


async def test_send_back_reopens_the_engine_task(
        client, admin_auth, seed, session_factory):
    """A3-06 on a real routing: the R row's engine task is active again and
    the department submits again."""
    from app.models.change import ChangeRoutingStandard
    from app.models.workflow import (
        Department, WfInstanceTask, WfStage, WfStep, WfStepRasic, WfTemplate)
    from app.services import assessment_checklist as checklist
    from tests.checklist_helpers import answered
    from tests.conftest import advance_to_assessment
    async with session_factory() as s:
        dep = {}
        for n in ("Tool Engineer", "Process Engineer"):
            d = Department(name=n, flow_type="change", is_active=True)
            s.add(d); await s.flush(); dep[n] = d.id
        t = WfTemplate(name="ECR-sb", description="x", version=1, is_active=True,
                       created_by=1)
        s.add(t); await s.flush()
        stage = WfStage(template_id=t.id, stage_order=1, name="S1")
        s.add(stage); await s.flush()
        step = WfStep(stage_id=stage.id, step_name="S1", position_in_stage=1)
        s.add(step); await s.flush()
        for n in dep:
            s.add(WfStepRasic(step_id=step.id, department_id=dep[n], rasic_letter="R"))
        s.add(ChangeRoutingStandard(change_type="tooling", template_id=t.id,
                                    template_version=1, updated_by=1))
        pa = Part(project_id=seed["project_id"], part_number="ART-SB-A", name="A",
                  part_type="internal_mfg", created_by=seed["admin_id"])
        pb = Part(project_id=seed["project_id"], part_number="ART-SB-B", name="B",
                  part_type="internal_mfg", created_by=seed["admin_id"])
        s.add_all([pa, pb])
        await s.commit()
        pa_id, pb_id = pa.id, pb.id
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "send back",
        "change_type": "tooling", "lead_id": seed["engineer_id"]},
        headers=admin_auth)
    cid = res.json()["id"]
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": pa_id, "is_lead": True}, headers=admin_auth)
    await advance_to_assessment(client, admin_auth, session_factory, cid)
    did = dep["Tool Engineer"]
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == did))).scalar_one()
        assert row.wf_instance_task_id is not None
        rid, tid = row.id, row.wf_instance_task_id
    keys = [i["key"] for i in checklist.items_for("Tool Engineer")]
    body = {"department_id": did, "verdict": "feasible",
            "details": {"impacts": answered("Tool Engineer", yes=keys[:1])}}
    res = await client.post(f"/api/v1/changes/{cid}/assessments", json=body,
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(WfInstanceTask, tid)).status == "approved"
    res = await client.post(f"/api/v1/changes/{cid}/impacted-items", json={
        "part_id": pb_id, "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        task = await s.get(WfInstanceTask, tid)
        a = await s.get(ChangeAssessment, rid)
        assert task.status == "active" and task.completed_at is None
        assert a.submitted_at is None and a.verdict == "pending"
        assert a.effective_status == "active"
    res = await client.post(f"/api/v1/changes/{cid}/assessments", json=body,
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(WfInstanceTask, tid)).status == "approved"
