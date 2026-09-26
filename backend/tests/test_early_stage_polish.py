"""Spec 2026-09-25 §16: early stages polish (capture, scoping, assessment)."""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.models.change import (
    ChangeAssessment, ChangeChangelog, ChangeRequest, ChangeRoutingStandard,
)
from app.models.entities import AuditLog, User
from app.models.workflow import (
    Department, UserDepartment, WfInstance, WfStage, WfStep, WfStepRasic, WfTemplate,
)
from tests.conftest import (
    advance_to_assessment, approve_gates, lock_impact, login, satisfy_capture_gate,
)

pytestmark = pytest.mark.asyncio
ACTS = "X-Acts-As-Department"


@pytest_asyncio.fixture
async def depts(session_factory, seed):
    """The ECR roles, and a two-stage physical-part standard: stage 1
    Development R + Tool Engineer R, stage 2 Project Manager R + Sales A +
    Development C (the commercial stage §16 keeps dormant during
    assessment; Development holds rows in both stages). The admin
    is a member of the assessing departments."""
    names = ["Development", "Tool Engineer", "Project Manager", "Sales",
             "Packaging Engineer", "APQP"]
    async with session_factory() as s:
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=(n == "Sales"))
            s.add(d); await s.flush(); ids[n] = d.id
        t = WfTemplate(name="ECM Assessment (Physical Part)", description="x",
                       version=1, is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [(1, [("Development", "R"), ("Tool Engineer", "R")]),
                  (2, [("Project Manager", "R"), ("Sales", "A"), ("Development", "C")])]
        for order, deps in layout:
            st = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
            s.add(st); await s.flush()
            step = WfStep(stage_id=st.id, step_name=f"S{order}", position_in_stage=1)
            s.add(step); await s.flush()
            for n, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=ids[n], rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        for n in ("Development", "Tool Engineer"):
            s.add(UserDepartment(user_id=seed["admin_id"], department_id=ids[n]))
        await s.commit()
    return ids


@pytest_asyncio.fixture
async def auth(client):
    return await login(client, "admin@test.io")


@pytest_asyncio.fixture
async def lead_auth(client):
    # The engineer is the change lead below (login mints an admin cookie; the
    # lead rules are by user id).
    return await login(client, "eng@test.io")


def acting(auth, dept_id):
    return {**auth, ACTS: str(dept_id)}


_n = {"i": 0}


async def _part(client, auth, seed, number=None, **extra):
    _n["i"] += 1
    number = number or f"ES-{_n['i']}"
    res = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": number, "name": f"Name {number}",
        "part_type": "internal_mfg", "item_category": "article", **extra}, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _change(client, auth, seed, lead=True, **over):
    body = {"project_id": seed["project_id"], "title": "early", "change_type": "physical_part",
            "reason": "r", "customer_relevant": True}
    if lead:
        body["lead_id"] = seed["engineer_id"]
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _in_assessment(client, auth, seed, session_factory):
    c = await _change(client, auth, seed)
    await approve_gates(client, auth, c["id"])
    pid = await _part(client, auth, seed)
    res = await client.post(f"/api/v1/changes/{c['id']}/impacted-items",
                            json={"part_id": pid}, headers=auth)
    assert res.status_code == 200, res.text
    await advance_to_assessment(client, auth, session_factory, c["id"])
    return c["id"]


async def _submit(client, auth, cid, dept_id, verdict="feasible"):
    res = await client.post(f"/api/v1/changes/{cid}/assessments",
                            json={"department_id": dept_id, "verdict": verdict}, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _state(client, auth, cid):
    res = await client.get(f"/api/v1/changes/{cid}/stage-state", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


# ---- P1-2: later stages dormant during assessment ---------------------------

async def test_later_stages_dormant_until_costing(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    await _submit(client, auth, cid, depts["Development"])
    await _submit(client, auth, cid, depts["Tool Engineer"])
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid))).scalar_one()
        assert inst.current_stage_order == 1
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all()
        later = [a for a in rows if a.stage_order == 2]
        assert later and all(a.effective_status == "pending" for a in later)

    # No assessment work for PM or Sales, neither in My Tasks nor the cockpit.
    for d in ("Sales", "Project Manager"):
        tasks = (await client.get("/api/v1/changes/my-tasks",
                                  headers=acting(auth, depts[d]))).json()
        assert not [t for t in tasks if t["kind"] == "assessment" and t["change_id"] == cid]
        acts = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                                 headers=acting(auth, depts[d]))).json()["actions"]
        assert not [a for a in acts if a["kind"] == "assessment"]

    st = await _state(client, auth, cid)
    a = st["assessment"]
    assert (a["total"], a["submitted"], a["all_submitted"]) == (2, 2, True)
    assert a["waiting_on"] == [] and a["can_close"] is True
    assert {v["verdict_label"] for v in a["verdicts"]} == {"Feasible"}

    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid))).scalar_one()
        assert inst.current_stage_order == 2


async def test_waiting_on_counts_first_stage_only(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    await _submit(client, auth, cid, depts["Development"])
    st = await _state(client, auth, cid)
    a = st["assessment"]
    assert (a["total"], a["submitted"], a["all_submitted"]) == (2, 1, False)
    assert [d["department_name"] for d in a["waiting_on"]] == ["Tool Engineer"]
    wait = next(w for w in st["waits"] if w["kind"] == "assessment_waiting")
    assert wait["text"] == "Assessment: waiting on Tool Engineer (1/2)"
    assert a["can_close"] is False


# ---- P1-3: "not our responsibility" re-letters only on approval --------------

async def test_decline_keeps_letter_until_approved(
        client, auth, lead_auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    dev = depts["Development"]
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation", json={
        "op": "reletter", "department_id": dev, "rasic_letter": "C",
        "reason": "Tooling only"}, headers=acting(auth, dev))
    assert res.status_code == 200, res.text
    row = next(d for st in res.json()["stages"] for d in st["departments"]
               if d["department_id"] == dev)
    assert row["rasic_letter"] == "R" and row["pending_rasic_letter"] == "C"

    st = await _state(client, auth, cid)
    assert [d["department_id"] for d in st["assessment"]["declined_pending"]] == [dev]
    assert any(w["text"] == "Development: declined, awaiting decision" for w in st["waits"])
    # Still owed: the workflow does not advance on a pending decline.
    assert dev in [d["department_id"] for d in st["assessment"]["waiting_on"]]
    assert st["routing_deviation"]["decider"] == "lead"
    assert st["routing_deviation"]["decider_user_id"] == seed["engineer_id"]

    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation/approve",
                            headers=lead_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid, ChangeAssessment.department_id == dev,
            ChangeAssessment.stage_order == 1))).scalar_one()
        assert a.rasic_letter == "C" and a.pending_rasic_letter is None


async def test_decline_rejected_restores_nothing_and_refused_after_answer(
        client, auth, lead_auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    dev, tool = depts["Development"], depts["Tool Engineer"]
    await client.post(f"/api/v1/changes/{cid}/routing/deviation", json={
        "op": "reletter", "department_id": dev, "rasic_letter": "C",
        "reason": "not ours"}, headers=acting(auth, dev))
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation/reject",
                            json={"reason": "it is yours"}, headers=lead_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid, ChangeAssessment.department_id == dev,
            ChangeAssessment.stage_order == 1))).scalar_one()
        assert a.rasic_letter == "R" and a.pending_rasic_letter is None
    await _submit(client, auth, cid, tool)
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation", json={
        "op": "reletter", "department_id": tool, "rasic_letter": "C",
        "reason": "late"}, headers=acting(auth, tool))
    assert res.status_code == 400
    assert "already submitted" in res.json()["detail"]


# ---- P1-4: transition rights ---------------------------------------------------

async def test_transition_rights_assessment(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    dev = acting(auth, depts["Development"])
    for body in ({"to_status": "rejected", "rejection_reason": "x"},
                 {"to_status": "cancelled", "cancellation_reason": "x"},
                 {"to_status": "on_hold"}, {"to_status": "costing"},
                 {"to_status": "scoping"}):
        res = await client.post(f"/api/v1/changes/{cid}/transition", json=body, headers=dev)
        assert res.status_code == 403, (body, res.text)
    st = await _state(client, dev, cid)
    assert not any(st["can_transition"].values())
    pm = acting(auth, depts["Project Manager"])
    st = await _state(client, pm, cid)
    assert st["can_transition"]["rejected"] is True
    res = await client.post(f"/api/v1/changes/{cid}/transition", json={
        "to_status": "rejected", "rejection_reason": "no business case"}, headers=pm)
    assert res.status_code == 200, res.text


async def test_transition_rights_capture(client, auth, seed, depts, session_factory):
    c = await _change(client, auth, seed)
    await satisfy_capture_gate(client, auth, c["id"])
    tool = acting(auth, depts["Tool Engineer"])
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "scoping"}, headers=tool)
    assert res.status_code == 403
    assert "Sales" in res.json()["detail"]
    sales = acting(auth, depts["Sales"])
    st = await _state(client, sales, c["id"])
    assert st["can_transition"]["scoping"] and st["can_transition"]["rejected"]
    assert not st["can_transition"]["cancelled"]
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "scoping"}, headers=sales)
    assert res.status_code == 200, res.text


# ---- P1-5: impact edits, lead ---------------------------------------------------

async def test_impact_edits_lead_pm_admin(client, auth, seed, depts, session_factory):
    c = await _change(client, auth, seed)
    pid = await _part(client, auth, seed)
    res = await client.post(f"/api/v1/changes/{c['id']}/impacted-items",
                            json={"part_id": pid}, headers=acting(auth, depts["Development"]))
    assert res.status_code == 403
    pm = acting(auth, depts["Project Manager"])
    res = await client.post(f"/api/v1/changes/{c['id']}/impacted-items",
                            json={"part_id": pid}, headers=pm)
    assert res.status_code == 200, res.text
    pid2 = await _part(client, auth, seed)
    res = await client.put(f"/api/v1/changes/{c['id']}/impacted-items",
                           json={"part_ids": [pid, pid2]}, headers=pm)
    assert res.status_code == 200, res.text
    # PM sets the lead.
    res = await client.patch(f"/api/v1/changes/{c['id']}",
                             json={"lead_id": seed["admin_id"]}, headers=pm)
    assert res.status_code == 200, res.text


async def test_kickoff_needs_a_lead(client, auth, seed, depts, session_factory):
    c = await _change(client, auth, seed, lead=False)
    st = await _state(client, auth, c["id"])
    assert any(w["kind"] == "no_lead" and w["text"] == "No lead assigned" for w in st["waits"])
    kick = next(w for w in st["waits"] if w["kind"] == "kickoff_missing")
    assert "change lead" in kick["missing"] and "quote deadline" in kick["missing"]
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 400
    assert "change lead" in res.json()["detail"] and "—" not in res.json()["detail"]


# ---- P1-1: checklist draft --------------------------------------------------------

async def test_checklist_draft_roundtrip(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    dev = depts["Development"]
    async with session_factory() as s:
        aid = (await s.execute(select(ChangeAssessment.id).where(
            ChangeAssessment.change_id == cid, ChangeAssessment.department_id == dev,
            ChangeAssessment.stage_order == 1))).scalar_one()
    draft = {"impacts": [{"key": "article_design_update", "answer": "yes",
                          "choice": {"value": "internal"}}], "notes": "wip"}
    res = await client.put(f"/api/v1/changes/{cid}/assessments/{aid}/draft",
                           json={"draft": draft}, headers=acting(auth, dev))
    assert res.status_code == 200, res.text
    res = await client.get(f"/api/v1/changes/{cid}/assessments/{aid}/draft",
                           headers=acting(auth, dev))
    assert res.json()["draft"] == draft and res.json()["saved_by"] == seed["admin_id"]
    other = acting(auth, depts["Sales"])
    assert (await client.put(f"/api/v1/changes/{cid}/assessments/{aid}/draft",
                             json={"draft": {}}, headers=other)).status_code == 403
    # The detail endpoint carries it too (restored on load).
    detail = (await client.get(f"/api/v1/changes/{cid}", headers=auth)).json()
    row = next(a for a in detail["assessments"] if a["id"] == aid)
    assert row["details"]["draft"]["data"] == draft
    await _submit(client, auth, cid, dev)
    res = await client.get(f"/api/v1/changes/{cid}/assessments/{aid}/draft", headers=auth)
    assert res.json()["draft"] is None


# ---- P2: packaging checklist, costing owed -------------------------------------------

async def test_packaging_checklist_and_not_impacted_owes_no_costing(
        client, auth, seed, depts):
    res = await client.get("/api/v1/changes/reference/assessment-checklist",
                           params={"department_id": depts["Packaging Engineer"]}, headers=auth)
    keys = {i["key"] for i in res.json()}
    assert {"layout_change", "packaging_type_change", "packaging_modification"} <= keys
    from app.services.change_service import ChangeService
    import json as _json
    a = ChangeAssessment(details=_json.dumps({"impacted": False}))
    assert ChangeService.owes_costing_input(a) is False


# ---- P2: cost carrier at the scoping meeting ---------------------------------------

async def test_cost_carrier_confirmed_at_meeting(client, auth, seed, depts, session_factory):
    c = await _change(client, auth, seed)
    pid = await _part(client, auth, seed)
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items",
                      json={"part_id": pid}, headers=auth)
    await satisfy_capture_gate(client, auth, c["id"])
    assert (await client.post(f"/api/v1/changes/{c['id']}/transition",
                              json={"to_status": "scoping"}, headers=auth)).status_code == 200
    await lock_impact(session_factory, c["id"])
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=depts["Sales"]))
        await s.commit()
    m = (await client.post(f"/api/v1/changes/{c['id']}/meetings", json={
        "department_rasic": {str(depts["Development"]): "R"}}, headers=auth)).json()
    st = await _state(client, auth, c["id"])
    assert any(w["kind"] == "cost_carrier_unconfirmed" for w in st["waits"])
    res = await client.post(f"/api/v1/changes/{c['id']}/meetings/{m['id']}/decide",
                            json={"decision": "proceed"}, headers=auth)
    assert res.status_code == 400 and "cost carrier" in res.json()["detail"]
    res = await client.patch(f"/api/v1/changes/{c['id']}/meetings/{m['id']}",
                             json={"cost_carrier": "internal"}, headers=auth)
    assert res.status_code == 200 and res.json()["cost_carrier"] == "internal"
    res = await client.post(f"/api/v1/changes/{c['id']}/meetings/{m['id']}/decide",
                            json={"decision": "proceed"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, c["id"])
        assert ch.customer_relevant is False and ch.status == "in_assessment"
        log = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == c["id"],
            ChangeChangelog.action == "cost_carrier_changed"))).scalars().all()
        assert len(log) == 1 and "Customer change to Internal change" in log[0].action_description
        from app.models.notification import Notification
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"]))).scalars().all()
        assert any("Cost carrier changed" in n.title for n in notes)


# ---- P2: concern settle record, risk labels ------------------------------------------

async def test_cancel_vote_settle_record(client, auth, seed, depts, session_factory):
    c = await _change(client, auth, seed)
    await satisfy_capture_gate(client, auth, c["id"])
    await client.post(f"/api/v1/changes/{c['id']}/transition",
                      json={"to_status": "scoping"}, headers=auth)
    r1 = (await client.post(f"/api/v1/changes/{c['id']}/concerns", json={
        "kind": "reject_proposal", "note": "too late"}, headers=auth)).json()
    st = await _state(client, auth, c["id"])
    assert any(w["kind"] == "open_cancel_votes" for w in st["waits"])
    res = await client.post(f"/api/v1/changes/{c['id']}/concerns/{r1['id']}/withdraw",
                            json={}, headers=auth)
    assert res.status_code == 200, res.text
    assert res.json()["settled_as"] == "author"
    assert res.json()["settled_label"] == "Withdrawn by author"
    r2 = (await client.post(f"/api/v1/changes/{c['id']}/concerns", json={
        "kind": "reject_proposal", "note": "again"}, headers=auth)).json()
    res = await client.post(f"/api/v1/changes/{c['id']}/concerns/{r2['id']}/withdraw",
                            json={}, headers=acting(auth, depts["Project Manager"]))
    assert res.status_code == 200, res.text
    assert res.json()["settled_label"] == "Settled by Project Management"


async def test_risk_type_label_in_register_and_audit(
        client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    res = await client.post(f"/api/v1/changes/{cid}/concerns", json={
        "kind": "risk", "note": "clip C5 marginal", "department_id": depts["Development"],
        "risk_type": "tolerance_stack", "severity": 3}, headers=auth)
    assert res.status_code == 200, res.text
    assert res.json()["risk_type_label"] == "Tolerance stack"
    rows = (await client.get(f"/api/v1/changes/{cid}/concerns", headers=auth)).json()
    assert rows[0]["risk_type_label"] == "Tolerance stack"
    st = await _state(client, auth, cid)
    assert st["assessment"]["open_risks"][0]["risk_type_label"] == "Tolerance stack"
    async with session_factory() as s:
        e = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "concern_raised"))).scalar_one()
        assert "Tolerance stack" in e.action_description
        assert "Tolerance stack" in e.new_value


async def test_reference_labels(client, auth, seed):
    res = await client.get("/api/v1/changes/reference/labels", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert body["verdict"]["feasible_with_conditions"]["en"] == "Feasible with conditions"
    assert body["change_type"]["physical_part"]["en"] == "Physical part"
    assert body["priority"]["medium"]["en"] == "Medium"


# ---- P1-7 / P1-8: end states, not feasible -------------------------------------------

async def test_end_state_rejected_and_cancelled(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    res = await client.post(f"/api/v1/changes/{cid}/transition", json={
        "to_status": "rejected", "rejection_reason": "no case"}, headers=auth)
    assert res.status_code == 200, res.text
    end = (await _state(client, auth, cid))["end_state"]
    assert end["kind"] == "rejected" and end["stopped_at"] == "in_assessment"
    assert end["stopped_at_label"] == "In Assessment" and end["reason"] == "no case"

    c = await _change(client, auth, seed)
    await client.post(f"/api/v1/changes/{c['id']}/transition",
                      json={"to_status": "on_hold"}, headers=auth)
    await client.post(f"/api/v1/changes/{c['id']}/transition", json={
        "to_status": "cancelled", "cancellation_reason": "dup"}, headers=auth)
    end = (await _state(client, auth, c["id"]))["end_state"]
    assert end["kind"] == "cancelled" and end["stopped_at"] == "captured"


async def test_not_feasible_with_ppt_listed(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    dev = depts["Development"]
    async with session_factory() as s:
        aid = (await s.execute(select(ChangeAssessment.id).where(
            ChangeAssessment.change_id == cid, ChangeAssessment.department_id == dev,
            ChangeAssessment.stage_order == 1))).scalar_one()
    res = await client.post(f"/api/v1/changes/{cid}/attachments", files={
        "file": ("change.pptx", b"deck", "application/octet-stream")},
        data={"kind": "change_ppt", "assessment_id": str(aid)}, headers=auth)
    assert res.status_code in (200, 201), res.text
    await _submit(client, auth, cid, dev, "not_feasible")
    st = await _state(client, auth, cid)
    nf = st["assessment"]["not_feasible"]
    assert nf == [{"department_id": dev, "department_name": "Development",
                   "assessment_id": aid, "rasic_letter": "R", "has_change_ppt": True}]
    assert any(w["text"] == "Development: not feasible (Change PPT)" for w in st["waits"])


# ---- P1-9: audit by entity ----------------------------------------------------------

async def test_audit_trail_by_entity_and_break_scope(client, auth, seed, depts, session_factory):
    a = await _change(client, auth, seed)
    b = await _change(client, auth, seed)
    # Another change's row carrying THIS change's number (a reused number).
    from app.services.audit_service import AuditService
    async with session_factory() as s:
        await AuditService.record(s, entity_type="wf_instance", entity_id=999999,
                                  action="wf_started", correlation_id=a["change_number"])
        await s.commit()
    rows = (await client.get("/api/v1/audit", params={"change_id": a["id"]},
                             headers=auth)).json()
    assert rows and all(r["entity_type"] == "change" and r["entity_id"] == a["id"]
                        for r in rows)
    v = (await client.get("/api/v1/audit/verify", params={"change_id": a["id"]},
                          headers=auth)).json()
    assert v["break_scope"] == "none" and v["change_ok"] is True
    async with session_factory() as s:
        other = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "change", AuditLog.entity_id == b["id"])
            .order_by(AuditLog.id))).scalars().first()
        await s.execute(update(AuditLog).where(AuditLog.id == other.id)
                        .values(action="tampered"))
        await s.commit()
    v = (await client.get("/api/v1/audit/verify", params={"change_id": a["id"]},
                          headers=auth)).json()
    assert v["valid"] is False
    # a's rows were written before b's: a break at b's row is not a's.
    assert v["break_scope"] == "global" and v["change_ok"] is True
    v = (await client.get("/api/v1/audit/verify", params={"change_id": b["id"]},
                          headers=auth)).json()
    assert v["break_scope"] == "change" and v["change_first_broken_id"] == other.id


# ---- P2: atomic items on create, title follows the lead -----------------------------

async def test_create_with_items_title_follows_lead(client, auth, seed, depts, session_factory):
    p1 = await _part(client, auth, seed, "20-1", customer_part_number="C1")
    p2 = await _part(client, auth, seed, "20-2", customer_part_number="C2")
    c = await _change(client, auth, seed, title="anything",
                      impacted_part_ids=[p1, p2], lead_part_id=p2)
    assert c["title"] == "20-2 +1 - C2 - Name 20-2" and c["title_auto"] is True
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    items = {i["part_id"]: i for i in detail["impacted_items"]}
    assert set(items) == {p1, p2} and items[p2]["is_lead"]

    res = await client.post(
        f"/api/v1/changes/{c['id']}/impacted-items/{items[p1]['id']}/make-lead",
        headers=auth)
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "20-1 +1 - C1 - Name 20-1"
    async with session_factory() as s:
        e = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == c["id"],
            ChangeChangelog.action == "title_recomposed")
            .order_by(ChangeChangelog.id.desc()))).scalars().first()
        assert "20-2 +1" in e.old_value

    await client.patch(f"/api/v1/changes/{c['id']}", json={"title": "Typed"}, headers=auth)
    res = await client.post(
        f"/api/v1/changes/{c['id']}/impacted-items/{items[p2]['id']}/make-lead",
        headers=auth)
    assert res.json()["title"] == "Typed" and res.json()["title_auto"] is False


# ---- P2: impact edits after the quote --------------------------------------------------

async def test_post_quote_impact_edit(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(status="quoted"))
        await s.commit()
    pid = await _part(client, auth, seed)
    res = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                            json={"part_id": pid}, headers=auth)
    assert res.status_code == 400 and "reason" in res.json()["detail"]
    res = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                            json={"part_id": pid, "reason": "customer added a bracket"},
                            headers=auth)
    assert res.status_code == 200, res.text
    st = await _state(client, auth, cid)
    sc = st["scope_change"]
    assert sc["covered"] is False and sc["reason"] == "customer added a bracket"
    assert depts["Development"] in sc["department_ids"]
    assert any(w["kind"] == "scope_not_covered" for w in st["waits"])
    detail = (await client.get(f"/api/v1/changes/{cid}", headers=auth)).json()
    assert detail["scope_changed_after_quote"] is True
    tasks = (await client.get("/api/v1/changes/my-tasks",
                              headers=acting(auth, depts["Development"]))).json()
    row = next(t for t in tasks if t["kind"] == "costing_update" and t["change_id"] == cid)
    assert row["kind_label"] == "Costing update after scope change"


# ---- P2: attendees, my tasks ------------------------------------------------------------

@pytest.mark.filterwarnings("ignore")
async def test_attendee_filter_drops_non_people():
    from app.services.early_stage_service import EarlyStageService as E
    assert E.is_person_contact({"name": "christoph.demmler",
                                "email": "christoph.demmler@us.ktx.group"})
    for e in ({"name": "PLM2 service token", "email": "plm2-service@service.local"},
              {"name": "admin", "email": "admin"},
              {"name": "smoke-admin", "email": "smoke-admin@test.local"},
              {"name": "admin", "email": "admin@plm.local"},
              {"name": "live-verify", "email": "live-verify"}):
        assert not E.is_person_contact(e), e


async def test_my_tasks_have_labels_and_stage(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    tasks = (await client.get("/api/v1/changes/my-tasks",
                              headers=acting(auth, depts["Development"]))).json()
    mine = [t for t in tasks if t["change_id"] == cid and t["kind"] == "assessment"]
    assert len(mine) == 1
    assert mine[0]["kind_label"] == "Assessment"
    assert mine[0]["stage"] == "in_assessment" and mine[0]["stage_label"] == "In Assessment"


# ---- review follow-ups -----------------------------------------------------------------

async def test_deviation_ops_with_multi_stage_rows(
        client, auth, lead_auth, seed, depts, session_factory):
    """A department with rows in several stages: add / remove / re-letter act on
    the assessment-stage row, never a 500 on the second row."""
    cid = await _in_assessment(client, auth, seed, session_factory)
    dev, sales = depts["Development"], depts["Sales"]
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation", json={
        "op": "reletter", "department_id": dev, "rasic_letter": "C",
        "reason": "not ours"}, headers=acting(auth, dev))
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == dev))).scalars().all()
        by_stage = {a.stage_order: a for a in rows}
        assert by_stage[1].pending_rasic_letter == "C"
        assert by_stage[2].pending_rasic_letter is None
        # clear the pending proposal to allow the next ones
        for a in rows:
            a.pending_rasic_letter = None
        from app.models.change import ChangeRouting
        r = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == cid))).scalar_one()
        r.deviation_status = "approved"
        await s.commit()
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation", json={
        "op": "add", "department_id": sales, "rasic_letter": "R",
        "reason": "customer packaging spec"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        stages = sorted(a.stage_order for a in (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == sales))).scalars().all())
        assert stages == [1, 2]
        from app.models.change import ChangeRouting
        r = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == cid))).scalar_one()
        r.deviation_status = "approved"
        await s.commit()
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation", json={
        "op": "remove", "department_id": dev, "reason": "wrong"}, headers=auth)
    assert res.status_code == 200, res.text

    async def _dev_stages():
        async with session_factory() as s:
            return sorted(a.stage_order for a in (await s.execute(select(ChangeAssessment).where(
                ChangeAssessment.change_id == cid,
                ChangeAssessment.department_id == dev))).scalars().all())

    # A removal only requests: both rows stay (still owed) until the decision,
    # the routing view marks the assessment-stage row as pending removal.
    assert await _dev_stages() == [1, 2]
    marks = {st["stage_order"]: d["pending_removal"] for st in res.json()["stages"]
             for d in st["departments"] if d["department_id"] == dev}
    assert marks == {1: True, 2: False}
    res = await client.post(f"/api/v1/changes/{cid}/routing/deviation/approve",
                            headers=lead_auth)
    assert res.status_code == 200, res.text
    assert await _dev_stages() == [2]


async def test_back_to_scoping_after_not_feasible(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    dev = depts["Development"]
    async with session_factory() as s:
        aid = (await s.execute(select(ChangeAssessment.id).where(
            ChangeAssessment.change_id == cid, ChangeAssessment.department_id == dev,
            ChangeAssessment.stage_order == 1))).scalar_one()
    att = await client.post(f"/api/v1/changes/{cid}/attachments", files={
        "file": ("change.pptx", b"deck", "application/octet-stream")},
        data={"kind": "change_ppt", "assessment_id": str(aid)}, headers=auth)
    assert att.status_code in (200, 201), att.text
    await _submit(client, auth, cid, dev, "not_feasible")
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 400 and "reason" in res.json()["detail"]
    res = await client.post(f"/api/v1/changes/{cid}/transition", json={
        "to_status": "scoping", "reason": "reshape the rib"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert not (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all()
        log = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "assessment_superseded"))).scalars().all()
        assert len(log) == 1 and '"not_feasible"' in log[0].old_value
        from app.models.change import ChangeAttachment
        a = (await s.execute(select(ChangeAttachment).where(
            ChangeAttachment.id == att.json()["id"]))).scalar_one()
        assert a.assessment_id is None
    # the next proceed rebuilds routing
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_assessment"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all()


async def test_creator_does_not_name_the_lead(client, auth, seed, depts):
    from tests.conftest import KEEP_LEAD_RULE
    sales = {**acting(auth, depts["Sales"]), KEEP_LEAD_RULE: "1"}
    c = await _change(client, sales, seed)             # lead_id = engineer asked
    assert c["lead_id"] is None
    c = await _change(client, auth, seed)              # admin may name it
    assert c["lead_id"] == seed["engineer_id"]


async def test_lead_candidates(client, auth, seed, depts, session_factory):
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        for uname in ("pm.one", "pm.two"):
            u = User(organization_id=seed["org_id"], username=uname, email=f"{uname}@x.io",
                     full_name="Pat Miller", hashed_password=get_password_hash("x-secret-123"),
                     role="engineer", is_active=True, mfa_enabled=False)
            s.add(u); await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts["Project Manager"]))
        await s.commit()
    c = await _change(client, auth, seed)
    rows = (await client.get(f"/api/v1/changes/{c['id']}/lead-candidates",
                             headers=auth)).json()
    names = {r["name"] for r in rows}
    assert {"Pat Miller (pm.one)", "Pat Miller (pm.two)", "Engineer"} <= names
    cur = next(r for r in rows if r["id"] == seed["engineer_id"])
    assert cur["is_current"] and cur["is_default"] is False
    assert rows[0]["id"] == seed["engineer_id"]


async def test_meeting_rights_are_403_and_stage_state_says_so(
        client, auth, seed, depts, session_factory):
    c = await _change(client, auth, seed)
    await satisfy_capture_gate(client, auth, c["id"])
    await client.post(f"/api/v1/changes/{c['id']}/transition",
                      json={"to_status": "scoping"}, headers=auth)
    dev = acting(auth, depts["Development"])
    res = await client.post(f"/api/v1/changes/{c['id']}/meetings",
                            json={"channel": "meeting"}, headers=dev)
    assert res.status_code == 403
    assert (await _state(client, dev, c["id"]))["can_record_meeting"] is False
    assert (await _state(client, auth, c["id"]))["can_record_meeting"] is True
    # scoping -> approved is the mother plant's side track only
    assert (await _state(client, auth, c["id"]))["can_transition"]["approved"] is False


async def test_acting_as_drops_the_lead_privilege(client, auth, seed, depts):
    c = await _change(client, auth, seed, lead_id=seed["admin_id"])
    st = await _state(client, auth, c["id"])
    assert st["can_transition"]["cancelled"] is True
    st = await _state(client, acting(auth, depts["Development"]), c["id"])
    assert st["can_transition"]["cancelled"] is False


async def test_impact_objects_before_routing(client, auth, seed, depts):
    art = await _part(client, auth, seed)
    tool = await _part(client, auth, seed, item_category="tool")
    res = await client.post(f"/api/v1/parts/{tool}/relations", json={
        "to_part_id": art, "relation_type": "produces"}, headers=auth)
    assert res.status_code in (200, 201), res.text
    c = await _change(client, auth, seed)
    body = (await client.get(f"/api/v1/changes/{c['id']}/impact-objects",
                             params={"part_ids": str(art)}, headers=auth)).json()
    served = body["parts"][0]
    assert served["part_id"] == art
    assert [o["id"] for o in served["served_by"]] == [tool]
    assert served["served_by"][0]["type"] == "tool"
    assert any(d["department_name"] == "Tool Engineer" for d in body["departments"])


async def test_my_tasks_and_list_carry_mine_and_letters(
        client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    tasks = (await client.get("/api/v1/changes/my-tasks",
                              headers=acting(auth, depts["Development"]))).json()
    row = next(t for t in tasks if t["change_id"] == cid)
    assert row["status"] == "in_assessment" and row["rasic_letters"] == ["R", "C"]
    lead = await login(client, "eng@test.io")
    rows = (await client.get("/api/v1/changes", headers=lead)).json()
    assert next(r for r in rows if r["id"] == cid)["is_mine"] is True
    rows = (await client.get("/api/v1/changes", headers=acting(auth, depts["Sales"]))).json()
    assert next(r for r in rows if r["id"] == cid)["is_mine"] is False


async def test_internal_approval_freezes_the_plan(client, auth, seed, depts, session_factory):
    from app.services.change_service import ChangeService
    from app.services.pnl_service import PnlService
    from app.services.price_redaction import redact_changelog_row
    c = await _change(client, auth, seed)
    async with session_factory() as s:
        ch = await s.get(ChangeRequest, c["id"])
        ch.customer_relevant = False
        ch.status = "costing"
        admin = await s.get(User, seed["admin_id"])
        await ChangeService.approve_internal_costs(
            s, ch, admin, release_due_date=datetime(2027, 1, 31))
        await s.commit()
        frozen = await PnlService.internal_frozen(s, [c["id"]])
        assert "revenue" in frozen[c["id"]] and "internal" in frozen[c["id"]]
        row = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == c["id"],
            ChangeChangelog.action == "pnl_frozen"))).scalar_one()
        assert '"pnl": null' in redact_changelog_row(row)["new_value"]


async def test_audit_entries_read_as_names(client, auth, seed, depts, session_factory):
    cid = await _in_assessment(client, auth, seed, session_factory)
    await _submit(client, acting(auth, depts["Development"]), cid, depts["Development"])
    rows = (await client.get("/api/v1/audit", params={"change_id": cid},
                             headers=auth)).json()
    started = next(r for r in rows if r["action"] == "wf_started")
    assert started["display_values"]["template_id"] == "ECM Assessment (Physical Part)"
    approved = next(r for r in rows if r["action"] == "task_approved")
    assert approved["display_values"]["task_id"].startswith("Development")
    assert approved["acting_as_department_name"] == "Development"
