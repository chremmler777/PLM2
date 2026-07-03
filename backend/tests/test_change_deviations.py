import pytest
import pytest_asyncio
from sqlalchemy import select

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
    login = await client.post("/api/v1/auth/login", json={
        "email": "viewer2@test.io", "password": "viewer-secret-1"})
    viewer_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    c = await _change(client, eng_auth, seed)  # lead is the engineer (proposer)
    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "lead proposes"}, headers=eng_auth)).json()
    denied = await client.post(
        f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
        json={"decision": "approved"}, headers=viewer_auth)
    assert denied.status_code == 400
    assert "role" in denied.json()["detail"].lower()


async def test_blocked_transition_requires_approved_deviation(
        client, eng_auth, admin_auth, seed):
    c = await _change(client, eng_auth, seed)  # no impacted items -> guard blocks
    blocked = await client.post(f"/api/v1/changes/{c['id']}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400
    assert "deviation" in blocked.json()["detail"].lower()

    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations", json={
        "to_status": "in_assessment", "reason": "PPT only at capture"},
        headers=eng_auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
                      json={"decision": "approved"}, headers=admin_auth)

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
async def dev_departments(session_factory):
    from app.models.workflow import Department
    async with session_factory() as s:
        names = ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"]
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i)
            s.add(d); await s.flush(); ids[n] = d.id
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
            rasic_letter="R", stage_order=1)
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


async def test_deviation_remove_deletes_task(
        session_factory, seed, dev_ecr_template, dev_departments):
    """op=remove on an unsubmitted stage-1 R row deletes the assessment AND its
    task; with the last blocking task gone, stage 1 advances to stage 2."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)

    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Tool Engineer"])
        ))).scalar_one()
        task_id = row.wf_instance_task_id
        assert task_id is not None

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="remove",
            department_id=dev_departments["Tool Engineer"])
        await s.commit()

    async with session_factory() as s:
        gone = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Tool Engineer"])
        ))).scalar_one_or_none()
        assert gone is None
        assert await s.get(WfInstanceTask, task_id) is None
        # Removing the last open blocking task lets stage 1 advance to stage 2.
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid, WfInstance.status == "active"))).scalar_one()
        assert inst.current_stage_order == 2


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
            department_id=dev_departments["Tool Engineer"], rasic_letter="S")
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
            rasic_letter="R", stage_order=1)
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
            rasic_letter="R", stage_order=1)
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


async def test_deviation_add_existing_row_updates_task(
        session_factory, seed, dev_ecr_template, dev_departments):
    """op=add targeting a dept that ALREADY has a row (Quality C in stage 1)
    re-letters/re-stages the assessment AND updates its linked task consistently:
    C(noted) -> R makes the task actionable, active, with a due date."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    from app.models.workflow import WfInstanceTask
    cid = await _dev_seeded_change(session_factory, seed)
    await _dev_build_routing(session_factory, seed, cid)

    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=dev_departments["Quality"], rasic_letter="R", stage_order=1)
        await s.commit()

    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == dev_departments["Quality"])
        ))).scalar_one()
        assert row.rasic_letter == "R"
        assert row.stage_order == 1
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert task is not None
        assert task.rasic_letter == "R"
        assert task.is_actionable is True
        assert task.status == "active"
        assert task.due_date is not None
        assert task.stage_order == 1


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
            department_id=dev_departments["Quality"], rasic_letter="R")
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
