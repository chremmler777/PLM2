"""Task 1: change-scoped WfInstance + assessment->task link (read-through).
Task 2: change-aware workflow engine (start_change_workflow, gate skips).
Task 3: submit spawns the assessment instance; payload rows link lazily."""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import select
from app.models.workflow import (
    WfInstance, WfInstanceTask, WfTemplate, WfStage, WfStep, WfStepRasic,
    Department, UserDepartment,
)
from app.models.change import ChangeRequest, ChangeAssessment, ChangeRoutingStandard
from app.services.workflow_service import WorkflowService
from app.services.wf_seed_service import seed_change_workflows
from tests.conftest import approve_gates, ADMIN_PASSWORD


async def _mk_template(session):
    t = WfTemplate(name="ECM Bewertung Test", created_by=1)
    session.add(t)
    await session.flush()
    return t


@pytest.mark.asyncio
async def test_instance_can_be_change_scoped(session_factory, seed):
    async with session_factory() as session:
        t = await _mk_template(session)
        chg = ChangeRequest(change_number="C-E-001", title="x", reason="y",
                            change_type="physical_part",
                            project_id=seed["project_id"],
                            raised_by=seed["admin_id"])
        session.add(chg)
        await session.flush()
        inst = WfInstance(template_id=t.id, change_id=chg.id, part_revision_id=None,
                          status="active", current_stage_order=1,
                          started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        assert inst.change_id == chg.id and inst.part_revision_id is None


@pytest.mark.asyncio
async def test_assessment_links_to_task_and_reads_through(session_factory, seed):
    async with session_factory() as session:
        t = await _mk_template(session)
        chg = ChangeRequest(change_number="C-E-002", title="x", reason="y",
                            change_type="physical_part",
                            project_id=seed["project_id"],
                            raised_by=seed["admin_id"])
        dept = Department(name="R&D-E", flow_type="change")
        session.add_all([chg, dept])
        await session.flush()
        inst = WfInstance(template_id=t.id, change_id=chg.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        task = WfInstanceTask(instance_id=inst.id, stage_order=1, step_id=None,
                              department_id=dept.id, rasic_letter="R",
                              status="approved", is_actionable=True,
                              owner_id=seed["admin_id"],
                              due_date=datetime.utcnow() + timedelta(days=7))
        session.add(task)
        await session.flush()
        a = ChangeAssessment(change_id=chg.id, department_id=dept.id,
                             stage_order=1, rasic_letter="R", status="pending",
                             wf_instance_task_id=task.id)
        session.add(a)
        await session.flush()
        await session.refresh(a)
        # R/A execution state reads through from the task
        assert a.effective_status == "submitted"        # approved -> submitted
        assert a.effective_owner_id == seed["admin_id"]
        assert a.effective_due_date == task.due_date


@pytest.mark.asyncio
async def test_sc_assessment_derives_status_without_task_write(session_factory, seed):
    async with session_factory() as session:
        chg = ChangeRequest(change_number="C-E-003", title="x", reason="y",
                            change_type="physical_part",
                            project_id=seed["project_id"],
                            raised_by=seed["admin_id"])
        dept = Department(name="Log-E", flow_type="change")
        session.add_all([chg, dept])
        await session.flush()
        a = ChangeAssessment(change_id=chg.id, department_id=dept.id,
                             stage_order=2, rasic_letter="S", status="pending")
        session.add(a)
        await session.flush()
        await session.refresh(a)
        assert a.effective_status == "pending"          # no task yet -> own column
        a.submitted_at = datetime.utcnow()
        assert a.effective_status == "submitted"        # payload submitted


async def _ecm_template(session) -> WfTemplate:
    await seed_change_workflows(session)   # seeds "ECM Bewertung" + departments
    return (await session.execute(select(WfTemplate).where(
        WfTemplate.name == "ECM Bewertung"))).scalar_one()


async def _mk_change(session, seed, number: str) -> ChangeRequest:
    chg = ChangeRequest(change_number=number, title="x", reason="y",
                        change_type="physical_part",
                        project_id=seed["project_id"],
                        raised_by=seed["admin_id"])
    session.add(chg)
    await session.flush()
    return chg


@pytest.mark.asyncio
async def test_start_change_workflow_creates_stage1_tasks(session_factory, seed):
    async with session_factory() as session:
        tmpl = await _ecm_template(session)
        chg = await _mk_change(session, seed, "C-E-010")
        inst = await WorkflowService.start_change_workflow(
            session, chg.id, tmpl.id, seed["admin_id"])
        assert inst.change_id == chg.id and inst.part_revision_id is None
        assert inst.status == "active" and inst.current_stage_order == 1
        tasks = (await session.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id))).scalars().all()
        assert any(t.stage_order == 1 for t in tasks)
        # Idempotent: a second start returns the same active instance.
        again = await WorkflowService.start_change_workflow(
            session, chg.id, tmpl.id, seed["admin_id"])
        assert again.id == inst.id


@pytest.mark.asyncio
async def test_change_scoped_instance_skips_cad_evidence_gate(session_factory, seed):
    # Completing a stage-1 R task on a change-scoped instance must not raise the
    # 3D-evidence error (that rule applies to ECN revisions only) — and must not
    # blow up in _audit on a null part_revision_id.
    async with session_factory() as session:
        tmpl = await _ecm_template(session)
        chg = await _mk_change(session, seed, "C-E-011")
        inst = await WorkflowService.start_change_workflow(
            session, chg.id, tmpl.id, seed["admin_id"])
        task = (await session.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.stage_order == 1,
            WfInstanceTask.is_actionable == True,  # noqa: E712
            WfInstanceTask.rasic_letter == "R",
        ).limit(1))).scalars().first()
        assert task is not None
        # Force the CAD-evidence gate to actually be reached: flip the
        # backing step's requires_cad_evidence flag on. Without the
        # part_revision_id-is-not-None guard in complete_task, this would
        # raise "3D evidence required..." since no CAD file exists and
        # part_revision_id is None on a change-scoped instance.
        assert task.step_id is not None
        step = await session.get(WfStep, task.step_id)
        assert step is not None
        step.requires_cad_evidence = True
        await session.flush()
        # Grant the acting user membership in the task's department (honest
        # fixture: complete_task's 4-eyes guard is satisfied — stage 1 has no
        # prior stage — and the user legitimately belongs to the department).
        session.add(UserDepartment(user_id=seed["admin_id"],
                                   department_id=task.department_id))
        await session.flush()
        result = await WorkflowService.complete_task(
            session, task.id, "approved", "ok", seed["admin_id"])
        await session.refresh(task)
        assert task.status == "approved"
        assert result.status == "active"   # other stage-1 R tasks still open


async def _seed_two_stage_standard(session_factory, change_type="physical_part"):
    """Two-stage template mapped as the standard for ``change_type``:
    stage1 D1(R) + D2(C); stage2 D3(A) + D4(I). Returns the department id map."""
    async with session_factory() as s:
        names = ["E-D1", "E-D2", "E-D3", "E-D4"]
        dep = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="change", is_active=True, sort_order=i)
            s.add(d); await s.flush(); dep[n] = d.id
        t = WfTemplate(name="ECM Bewertung", description="x", version=1,
                       is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [(1, [("E-D1", "R"), ("E-D2", "C")]), (2, [("E-D3", "A"), ("E-D4", "I")])]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"S{order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=dep[name], rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type=change_type, template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
        return dep


@pytest.mark.asyncio
async def test_submit_spawns_assessment_instance_with_linked_stage1(
        client, session_factory, seed):
    dep = await _seed_two_stage_standard(session_factory)
    auth = {"Authorization": f"Bearer {(await client.post('/api/v1/auth/login', json={'email': 'admin@test.io', 'password': ADMIN_PASSWORD})).json()['access_token']}"}

    body = {"project_id": seed["project_id"], "title": "spawn", "change_type": "physical_part",
            "reason": "x", "lead_id": seed["admin_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"],
         "part_number": "ART-SP", "name": "ART-SP", "part_type": "internal_mfg",
         "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=auth)
    assert res.status_code == 200, res.text

    # Assert via a fresh session that submit spawned the change-scoped instance and
    # stage-1 assessments linked lazily to its tasks; stage-2 rows remain unlinked.
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == c["id"]))).scalar_one()
        assert inst.status == "active" and inst.current_stage_order == 1
        assert inst.part_revision_id is None

        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"]))).scalars().all()
        by_dep = {a.department_id: a for a in rows}
        # Stage 1 (R/C) rows: every one linked to a stage-1 task.
        for name in ("E-D1", "E-D2"):
            a = by_dep[dep[name]]
            assert a.stage_order == 1
            assert a.wf_instance_task_id is not None, f"{name} stage-1 row must link to a task"
        # Stage 2 (A) row exists, unlinked, pending. (D4 is I -> no row.)
        d3 = by_dep[dep["E-D3"]]
        assert d3.stage_order == 2
        assert d3.wf_instance_task_id is None
        assert d3.status == "pending"
        assert dep["E-D4"] not in by_dep

        # Read-through semantics for the stage-1 blocking (R) row: the ROW stays
        # pending, its linked TASK is active, effective_status reads "active".
        r_row = by_dep[dep["E-D1"]]
        assert r_row.status == "pending"
        task = await s.get(WfInstanceTask, r_row.wf_instance_task_id)
        assert task.status == "active"
        assert r_row.effective_status == "active"
