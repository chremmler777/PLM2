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
    async with session_factory() as s:
        told = (await s.execute(select(Notification).where(
            Notification.kind == "impact_edited"))).scalars().all()
        assert [n.user_id for n in told] == [locked["dev_user"]]
        assert "ART-LI-B" in told[0].body and "costing is open again" in told[0].body
        # A3-06 in costing (Christoph 2026-10-19): an impact-yes answer is
        # sent back, the notice says so (never a bare "Check your answer")
        body = told[0].body
        assert "Your assessment is open again" in body
        assert "Check your answer" not in body


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


async def _set_lead(session_factory, cid, user_id):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.lead_id = user_id
        await s.commit()


async def test_in_costing_an_impact_yes_answer_is_sent_back(
        client, admin_auth, locked, session_factory, seed):
    """A3-06 in costing (Christoph 2026-10-19: build it): the department whose
    objects moved and whose answer said impact yes steps back alone: its
    assessment is open again (answer kept), its costing reopens, the move to
    quoting waits on it, it sees the task in My Tasks, the lead is told."""
    await _set_lead(session_factory, locked["cid"], seed["engineer_id"])
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    from app.models.change import ChangeChangelog
    from app.services.change_routing_service import ChangeRoutingService
    async with session_factory() as s:
        c = await s.get(ChangeRequest, locked["cid"])
        assert c.status == "costing"                       # no whole-change step back
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        assert a.submitted_at is None and a.verdict == "pending"
        assert a.effective_status == "active"
        assert a.details_dict["impacts"][0]["impacted"] is True     # answer kept
        assert "mirror part B" in a.details_dict["sent_back"]["reason"]
        assert not a.details_dict.get("costing_finalized_at")
        assert await ChangeRoutingService.blocking_waiting(s, c) != []
        log = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == locked["cid"],
            ChangeChangelog.action == "assessment_sent_back"))).scalars().one()
        assert "mirror part B" in log.notes
        lead = (await s.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "assessment_sent_back"))).scalars().all()
        assert len(lead) == 1 and "mirror part B" in lead[0].body
    # the costing -> quoting hop names it (the lead sees who it waits on)
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        c = await ChangeService.get_change(s, locked["cid"])
        reasons = await ChangeService._guard_reasons(s, c, "quoting")
        assert any(r.key == "assessments_open" and "Development" in str(r)
                   for r in reasons), reasons
    # My Tasks of the department
    tasks = (await client.get("/api/v1/changes/my-tasks",
                              headers=locked["dev_auth"])).json()
    mine = [t for t in tasks if t["change_id"] == locked["cid"]
            and t["kind"] == "assessment"]
    assert len(mine) == 1, tasks
    # not finalizable before the new answer
    res = await client.post(
        _u(locked, f"/costing/departments/{locked['dev']}/finalize"),
        headers=locked["dev_auth"])
    assert res.status_code == 400
    # the department answers again, in costing
    from app.services import assessment_checklist as checklist
    from tests.checklist_helpers import answered
    first_key = checklist.items_for("Development")[0]["key"]
    # a client echoing the marker back does not keep the row "sent back"
    res = await client.post(_u(locked, "/assessments"), json={
        "department_id": locked["dev"], "verdict": "feasible",
        "details": {"impacts": answered("Development", yes=[first_key]),
                    "sent_back": {"reason": "x"}}},
        headers=locked["dev_auth"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        assert a.submitted_at is not None and "sent_back" not in a.details_dict
    detail = (await client.get(_u(locked), headers=admin_auth)).json()
    assert locked["dev"] in detail["costing_pending_department_ids"]


async def test_in_quoting_the_department_is_sent_back_after_the_step_back(
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
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        assert a.submitted_at is None and a.verdict == "pending"


async def test_switch_off_or_impact_no_or_quoted_sends_nothing_back(
        client, admin_auth, locked, session_factory, monkeypatch):
    """A3-06 negative: an impact-no answer stays submitted in costing (the
    notice names the lead); after the offer (quoted) the scope change runs,
    nothing is sent back; switch off: nothing either."""
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        a.details = json.dumps({"impacts": [{"key": "x", "answer": "no", "impacted": False}]})
        await s.commit()
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        assert a.submitted_at is not None and a.verdict == "feasible"
        assert "sent_back" not in a.details_dict
        body = (await s.execute(select(Notification.body).where(
            Notification.kind == "impact_edited"))).scalars().one()
        assert "tell " in body and "Your assessment is open again" not in body
        # impact yes again, but the offer is out: scope change, no send-back
        a.details = json.dumps({"impacts": [{"key": "x", "answer": "yes", "impacted": True}]})
        c = await s.get(ChangeRequest, locked["cid"])
        c.status = "quoted"
        await s.commit()
        item_b = (await s.execute(select(ChangeImpactedItem.id).where(
            ChangeImpactedItem.change_id == locked["cid"],
            ChangeImpactedItem.part_id == locked["b"]))).scalar_one()
    res = await client.delete(_u(locked, f"/impacted-items/{item_b}"),
                              params={"reason": "Customer dropped part B again"},
                              headers=admin_auth)
    assert res.status_code == 204, res.text
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == locked["cid"]))).scalars().one()
        assert a.submitted_at is not None and a.verdict == "feasible"
        c = await s.get(ChangeRequest, locked["cid"])
        c.status = "costing"
        await s.commit()
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
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


async def test_send_back_in_costing_reopens_the_engine_task(
        client, admin_auth, eng_auth, seed, session_factory):
    """A3-06 in costing on a real routing: the engine has moved past the
    assessment stage (instance completed); the R row's task is active again
    behind it, the department sees it in My Tasks and submits again, and
    nothing else of the engine moves."""
    from app.models.change import ChangeRoutingStandard
    from app.models.workflow import (
        Department, WfInstance, WfInstanceTask, WfStage, WfStep, WfStepRasic, WfTemplate)
    from app.services import assessment_checklist as checklist
    from app.services.early_stage_service import EarlyStageService
    from app.services.change_service import ChangeService
    from tests.checklist_helpers import answered
    from tests.conftest import advance_to_assessment
    async with session_factory() as s:
        dep = {}
        for n in ("Tool Engineer", "Process Engineer"):
            d = Department(name=n, flow_type="change", is_active=True)
            s.add(d); await s.flush(); dep[n] = d.id
        t = WfTemplate(name="ECR-sbc", description="x", version=1, is_active=True,
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
        pa = Part(project_id=seed["project_id"], part_number="ART-SBC-A", name="A",
                  part_type="internal_mfg", created_by=seed["admin_id"])
        pb = Part(project_id=seed["project_id"], part_number="ART-SBC-B", name="B",
                  part_type="internal_mfg", created_by=seed["admin_id"])
        s.add_all([pa, pb])
        await s.commit()
        pa_id, pb_id = pa.id, pb.id
    await make_department_member(session_factory, seed["engineer_id"], "Tool Engineer")
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "send back costing",
        "change_type": "tooling", "lead_id": seed["admin_id"]},
        headers=admin_auth)
    cid = res.json()["id"]
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": pa_id, "is_lead": True}, headers=admin_auth)
    await advance_to_assessment(client, admin_auth, session_factory, cid)
    bodies = {}
    for n, did in dep.items():
        keys = [i["key"] for i in checklist.items_for(n)]
        bodies[n] = {"department_id": did, "verdict": "feasible",
                     "details": {"impacts": answered(n, yes=keys[:1])}}
        res = await client.post(f"/api/v1/changes/{cid}/assessments", json=bodies[n],
                                headers=admin_auth)
        assert res.status_code == 200, res.text
    async with session_factory() as s:
        c = await ChangeService.get_change(s, cid)
        c.status = "costing"
        await EarlyStageService.wake_later_stages(s, c)
        await s.commit()
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid))).scalar_one()
        assert inst.status == "completed"
        tid = (await s.execute(select(ChangeAssessment.wf_instance_task_id).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == dep["Tool Engineer"]))).scalar_one()
    res = await client.post(f"/api/v1/changes/{cid}/impacted-items", json={
        "part_id": pb_id, "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(WfInstanceTask, tid)).status == "active"
        assert (await s.get(ChangeRequest, cid)).status == "costing"
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=eng_auth)).json()
    assert [t["kind"] for t in tasks if t["change_id"] == cid].count("assessment") == 1
    res = await client.post(f"/api/v1/changes/{cid}/assessments",
                            json=bodies["Tool Engineer"], headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(WfInstanceTask, tid)).status == "approved"
        assert (await s.get(WfInstance, inst.id)).status == "completed"
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=eng_auth)).json()
    assert not [t for t in tasks if t["change_id"] == cid and t["kind"] == "assessment"]


async def test_a_draft_in_costing_only_for_a_sent_back_answer(
        client, admin_auth, locked, session_factory):
    """A3-06: the sent-back department keeps a draft of its new answer in
    costing; any other row keeps none there (negative)."""
    async with session_factory() as s:
        aid = (await s.execute(select(ChangeAssessment.id).where(
            ChangeAssessment.change_id == locked["cid"]))).scalar_one()
    url = _u(locked, f"/assessments/{aid}/draft")
    draft = {"draft": {"details": {"impacts": []}}}
    res = await client.put(url, json=draft, headers=locked["dev_auth"])
    assert res.status_code == 400, res.text
    async with session_factory() as s:
        a = await s.get(ChangeAssessment, aid)
        a.submitted_at = None
        a.verdict = "pending"
        a.details = json.dumps({**a.details_dict, "sent_back": {"reason": "B added"}})
        await s.commit()
    res = await client.put(url, json=draft, headers=locked["dev_auth"])
    assert res.status_code == 200, res.text
