import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.conftest import login, lock_impact

pytestmark = pytest.mark.asyncio


async def test_deviation_model_persists(session_factory, seed):
    from app.models.change import (
        ChangeRequest, ChangeTransitionDeviation, TRANSITION_DEVIATION_STATUSES,
    )
    async with session_factory() as s:
        change = ChangeRequest(
            change_number="CR-D-1", project_id=seed["project_id"], title="d",
            change_type="physical_part", status="captured",
            raised_by=seed["engineer_id"])
        s.add(change); await s.flush()
        s.add(ChangeTransitionDeviation(
            change_id=change.id, to_status="in_assessment",
            reason="PPT only at this stage", proposed_by=seed["engineer_id"]))
        await s.commit()
        dev = (await s.execute(select(ChangeTransitionDeviation))).scalar_one()
    assert dev.status == "pending"
    assert dev.to_status == "in_assessment"
    assert TRANSITION_DEVIATION_STATUSES == ("pending", "approved", "rejected", "consumed")


async def _change(client, auth, seed, **over):
    body = {"project_id": seed["project_id"], "title": "dev flow",
            "change_type": "physical_part", "lead_id": seed["engineer_id"]}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_propose_and_admin_approves(client, eng_auth, admin_auth, seed):
    c = await _change(client, eng_auth, seed)
    res = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "PPT only"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    dev = res.json()
    assert dev["status"] == "pending"

    # 4-eyes: proposer cannot decide their own deviation
    veto = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "approved"}, headers=eng_auth)
    assert veto.status_code == 400
    assert "own" in veto.json()["detail"].lower()

    ok = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "approved", "note": "ok for capture-stage"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"

    listed = await client.get(f"/api/v1/changes/{c['id']}/deviations", headers=eng_auth)
    assert listed.json()[0]["status"] == "approved"


async def test_reject_and_duplicate_pending_blocked(client, eng_auth, admin_auth, seed):
    c = await _change(client, eng_auth, seed)
    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r1"}, headers=eng_auth)).json()
    dup = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r2"}, headers=eng_auth)
    assert dup.status_code == 400
    rej = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "rejected", "note": "not enough info"}, headers=admin_auth)
    assert rej.json()["status"] == "rejected"
    # after rejection a new proposal is allowed again
    again = await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "r3"}, headers=eng_auth)
    assert again.status_code == 200


async def test_viewer_cannot_be_second_signature(client, eng_auth, seed, session_factory):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        viewer = User(
            organization_id=seed["org_id"], username="viewer2", email="viewer2@test.io",
            full_name="Viewer", hashed_password=get_password_hash("viewer-secret-1"),
            role="viewer", is_active=True, mfa_enabled=False,
        )
        s.add(viewer)
        await s.commit()
    viewer_auth = await login(client, "viewer2@test.io")

    c = await _change(client, eng_auth, seed)  # lead is the engineer (proposer)
    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "lead proposes"}, headers=eng_auth)).json()
    denied = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "approved"}, headers=viewer_auth)
    assert denied.status_code == 400
    assert "role" in denied.json()["detail"].lower()


async def test_blocked_transition_requires_approved_deviation(
        client, eng_auth, admin_auth, seed, session_factory):
    c = await _change(client, eng_auth, seed)
    # Scoping needs something to scope, so list one item; the change still has
    # no deadline, which is what soft-blocks scoping -> in_assessment below.
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": f"ART-DEV{c['id']}",
        "name": "Dev part", "part_type": "internal_mfg"}, headers=eng_auth)
    assert part.status_code in (200, 201), part.text
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items",
                      json={"part_id": part.json()["id"], "is_lead": True},
                      headers=eng_auth)
    from tests.conftest import satisfy_capture_gate
    await satisfy_capture_gate(client, eng_auth, c["id"])
    scop = await client.post(f"/api/v1/changes/{c['id']}/transition",
                             json={"to_status": "scoping"}, headers=eng_auth)
    assert scop.status_code == 200, scop.text
    blocked = await client.post(f"/api/v1/changes/{c['id']}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400
    assert "deviation" in blocked.json()["detail"].lower()

    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "PPT only at capture"},
        headers=eng_auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
                      json={"decision": "approved"}, headers=admin_auth)

    # The deviation waives the soft guard only; the impact lock is a separate hard
    # gate (see test_assessment_impact_gate.py). Stamp it so this test stays about
    # deviation consumption.
    await lock_impact(session_factory, c["id"])
    ok = await client.post(f"/api/v1/changes/{c['id']}/transition",
                           json={"to_status": "in_assessment"}, headers=eng_auth)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "in_assessment"

    # deviation is consumed and cannot be reused
    listed = (await client.get(f"/api/v1/changes/{c['id']}/deviations",
                               headers=eng_auth)).json()
    assert listed[0]["status"] == "consumed"

    log = (await client.get(f"/api/v1/changes/{c['id']}/changelog",
                            headers=eng_auth)).json()
    assert any(e["action"] == "deviated_transition" for e in log)


# ---------------------------------------------------------------------------
# Phase E Task 5: routing deviations mutate engine tasks (add/remove/reletter)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def dev_departments(session_factory, seed):
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        names = ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"]
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i)
            s.add(d); await s.flush(); ids[n] = d.id
        # These tests drive submit_assessment/complete_task as the engineer
        # across every department below; grant membership in all of them so
        # complete_task's department-membership guard doesn't block them.
        for dept_id in ids.values():
            s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept_id))
        await s.commit()
        return ids


@pytest_asyncio.fixture
async def dev_ecr_template(session_factory, dev_departments):
    """Two-stage ECR: stage1 Tool Engineer(R) + Quality(C); stage2 APQP(A) + Sales(I)."""
    from app.models.workflow import WfTemplate, WfStage, WfStep, WfStepRasic
    from app.models.change import ChangeRoutingStandard
    async with session_factory() as s:
        t = WfTemplate(name="ECR", description="Engineering Change Request",
                       version=1, is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [
            (1, [("Tool Engineer", "R"), ("Quality", "C")]),
            (2, [("APQP", "A"), ("Sales", "I")]),
        ]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"Stage {order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"Step {order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=dev_departments[name],
                                  rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
        return t.id


async def _dev_seeded_change(session_factory, seed, *, change_type="physical_part",
                             number="CR-DVT-1"):
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = ChangeRequest(change_number=number, project_id=seed["project_id"],
                          title="t", change_type=change_type, status="captured",
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"])
        s.add(c); await s.flush()
        await s.commit()
        return c.id


@pytest_asyncio.fixture
async def dev_bornstage_template(session_factory, dev_departments):
    """Two-stage 'tooling' route: stage1 Tool Engineer(R); stage2 APQP(A) +
    Quality(A) — both stage-2 depts blocking, so the stage is 'born complete'
    once their early payload-submits are mirrored onto its fresh tasks."""
    from app.models.workflow import WfTemplate, WfStage, WfStep, WfStepRasic
    from app.models.change import ChangeRoutingStandard
    async with session_factory() as s:
        t = WfTemplate(name="ECR-born", description="born-complete repro",
                       version=1, is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [
            (1, [("Tool Engineer", "R")]),
            (2, [("APQP", "A"), ("Quality", "A")]),
        ]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"Stage {order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"Step {order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=dev_departments[name],
                                  rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="tooling", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
        return t.id


async def _dev_build_routing(session_factory, seed, cid):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"])
        await s.commit()


async def test_deviation_add_creates_task_in_running_instance(
        session_factory, seed, dev_ecr_template, dev_departments):
    """op=add on a started stage creates a NEW WfInstanceTask (active, actionable)
    in the change-scoped instance and links the new assessment row to it."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=dev_departments["Manufacturing Engineer"],
            rasic_letter="R", stage_order=1, reason="test add")
        await s.commit()

    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Manufacturing Engineer"])
        ))).scalar_one()
        assert row.wf_instance_task_id is not None
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert task.status == "active"
        assert task.is_actionable is True
        assert task.rasic_letter == "R"
        assert task.stage_order == 1
        # task belongs to the change-scoped instance
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid, WfInstance.status == "active"))).scalar_one()
        assert task.instance_id == inst.id
        assert row.effective_status == "active"


async def _dev_te_row(s, cid, dept_id):
    from app.models.change import ChangeAssessment
    return (await s.execute(select(ChangeAssessment).where(
        (ChangeAssessment.change_id == cid)
        & (ChangeAssessment.department_id == dept_id)
    ).execution_options(populate_existing=True))).scalar_one_or_none()


async def test_deviation_remove_waits_for_approval_then_deletes_task(
        session_factory, seed, dev_ecr_template, dev_departments):
    """op=remove is a request: the row and its active task stay (still owed,
    stage 1 does not advance) until the lead's decision. On approval the row
    and its task go, a document filed with the row stays on the change, the
    department leaves the snapshot, and stage 1 advances to stage 2."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAttachment, ChangeRouting
    from app.models.workflow import WfInstance, WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)
    te = dev_departments["Tool Engineer"]

    async with session_factory() as s:
        row = await _dev_te_row(s, cid, te)
        task_id, row_id = row.wf_instance_task_id, row.id
        assert task_id is not None
        att = ChangeAttachment(change_id=cid, filename="moldflow.pdf", stored_path="x",
                               content_type="application/pdf", size_bytes=1,
                               sha256="0" * 64, assessment_id=row_id,
                               uploaded_by=seed["engineer_id"])
        s.add(att)
        await s.commit()
        att_id = att.id

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="remove",
            department_id=te, reason="test op")
        await s.commit()

    async with session_factory() as s:
        row = await _dev_te_row(s, cid, te)
        assert row is not None and row.rasic_letter == "R"
        task = await s.get(WfInstanceTask, task_id)
        assert task.status == "active" and task.is_actionable
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid, WfInstance.status == "active"))).scalar_one()
        assert inst.current_stage_order == 1
        change = await s.get(ChangeRequest, cid)
        assert await ChangeRoutingService.pending_removal_ids(s, change) == {row_id}
        # Every gate still waits on the department.
        assert "Tool Engineer" in await ChangeRoutingService.blocking_waiting(s, change)
        # A second request for the same row is refused while it is pending.
        with pytest.raises(ValueError, match="already awaiting"):
            await ChangeRoutingService.apply_deviation(
                s, change, seed["admin_id"], op="remove",
                department_id=te, reason="again")

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"])
        await s.commit()

    async with session_factory() as s:
        assert await _dev_te_row(s, cid, te) is None
        assert await s.get(WfInstanceTask, task_id) is None
        att = await s.get(ChangeAttachment, att_id)
        assert att is not None and att.assessment_id is None
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == cid))).scalar_one()
        assert not any(d["department_id"] == te
                       for st in routing.standard_snapshot["stages"]
                       for d in st["departments"])
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid, WfInstance.status == "active"))).scalar_one()
        assert inst.current_stage_order == 2
        change = await s.get(ChangeRequest, cid)
        assert await ChangeRoutingService.pending_removal_ids(s, change) == set()


async def test_deviation_remove_rejected_keeps_the_row_owed(
        session_factory, seed, dev_ecr_template, dev_departments):
    """A rejected removal lapses: the row, its letter and its active task are
    untouched, the pending mark is gone, and the stage still waits on it."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest
    from app.models.workflow import WfInstance, WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)
    te = dev_departments["Tool Engineer"]
    async with session_factory() as s:
        row = await _dev_te_row(s, cid, te)
        task_id, row_id = row.wf_instance_task_id, row.id
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="remove",
            department_id=te, reason="test op")
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.reject_deviation(
            s, change, seed["admin_id"], "they are needed")
        await s.commit()
    async with session_factory() as s:
        row = await _dev_te_row(s, cid, te)
        assert row is not None and row.id == row_id and row.rasic_letter == "R"
        assert row.wf_instance_task_id == task_id
        task = await s.get(WfInstanceTask, task_id)
        assert task.status == "active"
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid, WfInstance.status == "active"))).scalar_one()
        assert inst.current_stage_order == 1
        change = await s.get(ChangeRequest, cid)
        assert await ChangeRoutingService.pending_removal_ids(s, change) == set()
        # The next removal request may be filed again.
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="remove",
            department_id=te, reason="second try")
        assert await ChangeRoutingService.pending_removal_ids(s, change) == {row_id}


async def test_deviation_remove_of_an_answered_row_is_refused_or_moot(
        session_factory, seed, dev_ecr_template, dev_departments):
    """An answered row cannot be taken off; one answered while its removal
    was pending stays on approval (its answer is on the record)."""
    from datetime import datetime
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)
    te = dev_departments["Tool Engineer"]
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="remove",
            department_id=te, reason="test op")
        row = await _dev_te_row(s, cid, te)
        row.verdict = "feasible"
        row.submitted_at = datetime.utcnow()
        row.submitted_by = seed["engineer_id"]
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"])
        await s.commit()
    async with session_factory() as s:
        assert await _dev_te_row(s, cid, te) is not None
        change = await s.get(ChangeRequest, cid)
        with pytest.raises(ValueError, match="already submitted"):
            await ChangeRoutingService.apply_deviation(
                s, change, seed["engineer_id"], op="remove",
                department_id=te, reason="late")


async def test_deviation_reletter_updates_task(
        session_factory, seed, dev_ecr_template, dev_departments):
    """op=reletter R->S flips the task to a non-actionable noted task and clears
    its due date; the assessment reads through the task's S semantics. Because
    the R->S removes the last OPEN actionable task in stage 1, the stage advances
    to stage 2."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="reletter",
            department_id=dev_departments["Tool Engineer"], rasic_letter="S", reason="test op")
        await s.commit()
    # Spec §16 P1-3: a re-letter is a request until it is approved.
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Tool Engineer"])
        ))).scalar_one()
        assert row.pending_rasic_letter == "S" and row.rasic_letter != "S"
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"])
        await s.commit()

    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Tool Engineer"])
        ))).scalar_one()
        assert row.rasic_letter == "S"
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert task.rasic_letter == "S"
        assert task.is_actionable is False
        assert task.status == "noted"
        assert task.due_date is None
        # S row with a live (started) task reads effective 'active' until submitted.
        assert row.effective_status == "active"
        # Relettering away the last open blocking task advances stage 1 -> 2.
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid, WfInstance.status == "active"))).scalar_one()
        assert inst.current_stage_order == 2


async def test_deviation_add_to_passed_stage_task_active_still_blocks(
        session_factory, seed, dev_ecr_template, dev_departments):
    """Decision pin: a deviation add targeting a PASSED stage still creates an
    active blocking task in that stage. The engine's current_stage_order does NOT
    move backwards, and even after the instance completes, blocking_complete stays
    False until the passed-stage deviation task is completed."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    from app.services.workflow_service import WorkflowService
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)

    # Submit stage-1 R (Tool Engineer) -> engine advances to stage 2.
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(
            s, change, dev_departments["Tool Engineer"], "feasible", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid, WfInstance.status == "active"))).scalar_one()
        assert inst.current_stage_order == 2

    # Add a blocking dept to the PASSED stage 1.
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=dev_departments["Manufacturing Engineer"],
            rasic_letter="R", stage_order=1, reason="test add")
        await s.commit()

    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Manufacturing Engineer"])
        ))).scalar_one()
        mfg_task_id = row.wf_instance_task_id
        assert mfg_task_id is not None
        task = await s.get(WfInstanceTask, mfg_task_id)
        assert task.status == "active"
        assert task.is_actionable is True
        assert task.stage_order == 1
        # current_stage_order must NOT move backward to the passed stage.
        inst = await s.get(WfInstance, task.instance_id)
        assert inst.current_stage_order == 2

    # Submit stage-2 A (APQP) -> stage 2 completes, instance completes. The
    # passed-stage deviation task is untouched (different stage) and still active.
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(
            s, change, dev_departments["APQP"], "feasible", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        # Instance done, yet blocking_complete is False: the passed-stage task gates it.
        assert await ChangeRoutingService.blocking_complete(s, change) is False

    # Complete the passed-stage deviation task -> blocking now complete.
    async with session_factory() as s:
        await WorkflowService.complete_task(
            s, mfg_task_id, "approved", "done", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        assert await ChangeRoutingService.blocking_complete(s, change) is True


async def test_born_complete_stage_advances_and_completes(
        session_factory, seed, dev_bornstage_template, dev_departments):
    """Regression: a stage born with all its actionable tasks already approved
    (from early payload-submits mirrored on creation) must NOT stall the
    instance. Stage-2 depts APQP(A)+Quality(A) submit early, then stage 1
    completes -> stage 2 is born complete -> the engine cascades past it and
    completes the instance; blocking_complete stays True."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    from app.models.change import ChangeRequest
    from app.models.workflow import WfInstance
    cid = await _dev_seeded_change(session_factory, seed,
                                   change_type="tooling", number="CR-DVT-BORN")
    await _dev_build_routing(session_factory, seed, cid)

    # Stage-2 A depts submit EARLY, before stage 2 starts (payload-only submits:
    # their tasks do not exist yet, so the rows go straight to 'submitted').
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(
            s, change, dev_departments["APQP"], "feasible", seed["engineer_id"])
        await ChangeService.submit_assessment(
            s, change, dev_departments["Quality"], "feasible", seed["engineer_id"])
        await s.commit()

    # Stage 1 completes -> stage 2 is created with both actionable tasks mirrored
    # to 'approved'. The loop must cascade past it and complete the instance.
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(
            s, change, dev_departments["Tool Engineer"], "feasible", seed["engineer_id"])
        await s.commit()

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid))).scalar_one()
        assert inst.status == "completed"
        assert await ChangeRoutingService.blocking_complete(s, change) is True


async def test_completing_passed_stage_task_emits_single_completion(
        session_factory, seed, dev_ecr_template, dev_departments):
    """A stray task completed in a PASSED stage of an already-completed instance
    must not re-emit wf_completed. Exactly one completion audit row exists."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    from app.services.workflow_service import WorkflowService
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import WfInstance
    from app.models.entities import AuditLog
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)

    # Advance to stage 2.
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(
            s, change, dev_departments["Tool Engineer"], "feasible", seed["engineer_id"])
        await s.commit()

    # Add a blocking dept to the PASSED stage 1.
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=dev_departments["Manufacturing Engineer"],
            rasic_letter="R", stage_order=1, reason="test add")
        await s.commit()

    # Submit stage-2 A -> stage 2 completes, instance completes (1st completion).
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(
            s, change, dev_departments["APQP"], "feasible", seed["engineer_id"])
        await s.commit()

    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Manufacturing Engineer"])
        ))).scalar_one()
        mfg_task_id = row.wf_instance_task_id

    # Complete the passed-stage deviation task on the already-completed instance.
    async with session_factory() as s:
        await WorkflowService.complete_task(
            s, mfg_task_id, "approved", "done", seed["engineer_id"])
        await s.commit()

    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid))).scalar_one()
        completions = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "wf_instance",
            AuditLog.entity_id == inst.id,
            AuditLog.action == "wf_completed"))).scalars().all()
        assert len(completions) == 1


async def test_deviation_add_on_an_existing_row_is_refused(
        session_factory, seed, dev_ecr_template, dev_departments):
    """op=add targeting a dept that ALREADY has a row (Quality C in stage 1)
    never re-letters it on the spot (review finding 2): the change of role
    is a reletter, which waits for the lead. Row and task stay as they were."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        with pytest.raises(ValueError, match="reletter"):
            await ChangeRoutingService.apply_deviation(
                s, change, seed["engineer_id"], op="add",
                department_id=dev_departments["Quality"], rasic_letter="R",
                stage_order=1, reason="test add")
        await s.rollback()

    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Quality"])
        ))).scalar_one()
        assert row.rasic_letter == "C" and row.pending_rasic_letter is None
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert task.rasic_letter == "C" and task.is_actionable is False


async def test_deviation_reletter_noted_to_blocking(
        session_factory, seed, dev_ecr_template, dev_departments):
    """op=reletter C->R flips a noted (non-actionable) task to a blocking one:
    is_actionable True, status active, due_date set."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="reletter",
            department_id=dev_departments["Quality"], rasic_letter="R", reason="test op")
        await s.commit()
    # Spec §16 P1-3: a re-letter is a request until it is approved.
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Quality"])
        ))).scalar_one()
        assert row.pending_rasic_letter == "R" and row.rasic_letter != "R"
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"])
        await s.commit()

    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Quality"])
        ))).scalar_one()
        assert row.rasic_letter == "R"
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert task.rasic_letter == "R"
        assert task.is_actionable is True
        assert task.status == "active"
        assert task.due_date is not None


# ---- four-eyes over the bundle; rejected add keeps its documents; Informed removal ----

async def _third_user(session_factory, seed):
    from app.models.entities import User
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="pm3", email="pm3@test.io",
                 full_name="PM Three", hashed_password=get_password_hash("pm3-secret-1"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        return u.id


async def test_nobody_who_filed_a_request_of_the_bundle_decides_it(
        session_factory, seed, dev_ecr_template, dev_departments):
    """The decision covers every request since the last decision. The lead
    filed one, then an admin filed another (the latest proposer): neither
    decides, a third person does, and a rejection tells both."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeRouting
    from app.models.notification import Notification
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)
    pm = await _third_user(session_factory, seed)
    lead, admin = seed["engineer_id"], seed["admin_id"]
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, lead, op="add", department_id=dev_departments["Manufacturing Engineer"],
            rasic_letter="R", stage_order=1, reason="lead asks")
        await ChangeRoutingService.apply_deviation(
            s, change, admin, op="remove", department_id=dev_departments["Quality"],
            reason="admin asks")
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == cid))).scalar_one()
        assert routing.deviation_proposed_by == admin
        with pytest.raises(ValueError, match="includes a request you filed"):
            await ChangeRoutingService.approve_deviation(s, change, lead)
        with pytest.raises(ValueError, match="your own"):
            await ChangeRoutingService.reject_deviation(s, change, admin, "no")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.reject_deviation(s, change, pm, "not now")
        await s.commit()
    async with session_factory() as s:
        told = set((await s.execute(select(Notification.user_id).where(
            Notification.kind == "routing_deviation_rejected"))).scalars().all())
        assert told == {lead, admin}


async def test_rejected_add_keeps_the_documents_filed_with_its_row(
        session_factory, seed, dev_ecr_template, dev_departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAttachment
    from app.models.workflow import WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)
    mfg = dev_departments["Manufacturing Engineer"]
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add", department_id=mfg,
            rasic_letter="R", stage_order=1, reason="needed?")
        row = await _dev_te_row(s, cid, mfg)
        task_id = row.wf_instance_task_id
        att = ChangeAttachment(change_id=cid, filename="study.pdf", stored_path="x",
                               content_type="application/pdf", size_bytes=1,
                               sha256="0" * 64, assessment_id=row.id,
                               uploaded_by=seed["engineer_id"])
        s.add(att)
        await s.commit()
        att_id = att.id
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.reject_deviation(s, change, seed["admin_id"], "no")
        await s.commit()
    async with session_factory() as s:
        assert await _dev_te_row(s, cid, mfg) is None
        assert await s.get(WfInstanceTask, task_id) is None
        att = await s.get(ChangeAttachment, att_id)
        assert att is not None and att.assessment_id is None


async def test_approved_removal_of_an_informed_department_leaves_the_snapshot(
        session_factory, seed, dev_ecr_template, dev_departments):
    """Sales is Informed (stage 2, no assessment row): taking it off the
    routing takes its I entry off the snapshot once approved, not before."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeRouting, ChangeChangelog
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)
    sales = dev_departments["Sales"]

    async def sales_entries(s):
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == cid).execution_options(
                populate_existing=True))).scalar_one()
        return [(st["stage_order"], d["rasic_letter"])
                for st in routing.standard_snapshot["stages"]
                for d in st["departments"] if d["department_id"] == sales]

    async with session_factory() as s:
        assert await sales_entries(s) == [(2, "I")]
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="remove", department_id=sales,
            reason="not informed")
        await s.commit()
    async with session_factory() as s:
        assert await sales_entries(s) == [(2, "I")]
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"])
        await s.commit()
    async with session_factory() as s:
        assert await sales_entries(s) == []
        entry = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "routing_deviation_approved"))).scalar_one()
        assert str(sales) in entry.new_value and "uninformed" in entry.new_value
