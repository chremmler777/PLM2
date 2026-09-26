# backend/tests/test_change_routing.py
import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from app.models.workflow import Department, WfTemplate, WfStage, WfStep, WfStepRasic
from app.models.change import (
    ChangeRouting, ChangeRoutingStandard, BLOCKING_LETTERS, TASK_LETTERS,
)
from tests.conftest import approve_gates, advance_to_assessment, login

pytestmark = pytest.mark.asyncio


async def test_routing_models_importable_and_columns_exist(session_factory):
    # Persisting a ChangeRoutingStandard + reading ChangeAssessment new columns proves the schema migrated.
    async with session_factory() as s:
        t = WfTemplate(name="ECR", description="x", version=1, is_active=True, created_by=1)
        s.add(t)
        await s.flush()
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
    assert BLOCKING_LETTERS == ("R", "A")
    assert TASK_LETTERS == ("R", "A", "S", "C", "I")
    from app.models.change import ASSESSMENT_LETTERS
    assert ASSESSMENT_LETTERS == ("R", "A", "S", "C")


@pytest_asyncio.fixture
async def departments(session_factory):
    async with session_factory() as s:
        names = ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"]
        ids = {}
        for i, n in enumerate(names):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i)
            s.add(d); await s.flush(); ids[n] = d.id
        await s.commit()
        return ids


@pytest_asyncio.fixture
async def departments_member(session_factory, seed, departments):
    """Grant the engineer (eng@test.io, driven via `_login`/`eng_auth`)
    membership in every department the `departments` fixture created.
    complete_task's department-membership guard requires this for the tests
    that submit blocking (R/A) assessments as that user; tests asserting
    no-membership behaviour (test_my_tasks_only_active_stage) or a custom
    membership set (test_my_tasks_active_stage_filter_exercised) don't use it."""
    from app.models.workflow import UserDepartment
    async with session_factory() as s:
        for dept_id in departments.values():
            s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept_id))
        await s.commit()
    return departments


@pytest_asyncio.fixture
async def ecr_template(session_factory, departments):
    """Two-stage ECR: stage1 Tool Engineer(R) + Quality(C); stage2 APQP(A) + Sales(I)."""
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
                s.add(WfStepRasic(step_id=step.id, department_id=departments[name], rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
        return t.id


async def test_resolve_standard_from_template(session_factory, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    async with session_factory() as s:
        tid, ver, stages = await ChangeRoutingService.resolve_standard(s, "physical_part")
        assert tid == ecr_template and ver == 1
        assert [st["stage_order"] for st in stages] == [1, 2]
        s1 = {d["department_id"]: d["rasic_letter"] for d in stages[0]["departments"]}
        assert s1[departments["Tool Engineer"]] == "R"
        assert s1[departments["Quality"]] == "C"


async def test_resolve_fallback_to_type_disciplines(session_factory, departments):
    from app.services.change_routing_service import ChangeRoutingService
    async with session_factory() as s:
        tid, ver, stages = await ChangeRoutingService.resolve_standard(s, "tooling")
        assert tid is None and ver is None
        assert len(stages) == 1 and stages[0]["stage_order"] == 1
        # all fallback departments are blocking R
        assert all(d["rasic_letter"] == "R" for d in stages[0]["departments"])
        assert len(stages[0]["departments"]) >= 1


async def _seeded_change(session_factory, seed, change_type="physical_part"):
    """Create a captured change with one impacted part, directly via models."""
    from app.models.change import ChangeRequest, ChangeImpactedItem
    from app.models.part import Part
    async with session_factory() as s:
        c = ChangeRequest(change_number="CR-T-1", project_id=seed["project_id"],
                          title="t", change_type=change_type, status="captured",
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"])
        s.add(c); await s.flush()
        await s.commit()
        return c.id


async def test_build_routing_generates_task_rows_excludes_informed(
        session_factory, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment, ChangeRouting
    from app.models.workflow import WfInstanceTask
    cid = await _seeded_change(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(ChangeAssessment.change_id == cid))).scalars().all()
        by_dep = {a.department_id: a for a in rows}
        # Sales is I -> no row; Tool Eng(R, stage1), Quality(C, stage1), APQP(A, stage2)
        assert departments["Sales"] not in by_dep
        te = by_dep[departments["Tool Engineer"]]
        assert te.stage_order == 1
        assert te.rasic_letter == "R"
        # New semantics: execution state lives on the engine task. The ROW stays
        # pending, its linked TASK is active, and effective_status reads "active".
        assert te.status == "pending"
        assert te.wf_instance_task_id is not None
        task = await s.get(WfInstanceTask, te.wf_instance_task_id)
        assert task.status == "active"
        assert te.effective_status == "active"
        # Stage 2 has not started: row pending, unlinked, effective pending.
        apqp = by_dep[departments["APQP"]]
        assert apqp.stage_order == 2
        assert apqp.status == "pending"
        assert apqp.wf_instance_task_id is None
        assert apqp.effective_status == "pending"
        routing = (await s.execute(select(ChangeRouting).where(ChangeRouting.change_id == cid))).scalar_one()
        assert routing.template_id == ecr_template
        assert len(routing.standard_snapshot["stages"]) == 2


async def test_build_routing_is_idempotent(
        session_factory, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment, ChangeRouting
    cid = await _seeded_change(session_factory, seed)
    # Build routing twice in separate sessions; the second call must be a no-op.
    for _ in range(2):
        async with session_factory() as s:
            change = await s.get(ChangeRequest, cid)
            await ChangeRoutingService.build_routing(s, change, seed["engineer_id"])
            await s.commit()
    async with session_factory() as s:
        routings = (await s.execute(select(ChangeRouting).where(ChangeRouting.change_id == cid))).scalars().all()
        assert len(routings) == 1
        rows = (await s.execute(select(ChangeAssessment).where(ChangeAssessment.change_id == cid))).scalars().all()
        # Three task rows (Tool Eng, Quality, APQP) — Sales(I) excluded; no duplication.
        assert len(rows) == 3


async def _login(client):
    return await login(client, "eng@test.io")


async def _login_admin(client):
    return await login(client, "admin@test.io")


async def _api_change_in_assessment(client, auth, seed, session_factory):
    body = {"project_id": seed["project_id"], "title": "Wall +0.2", "change_type": "physical_part",
            "reason": "sink", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-R1",
         "name": "ART-R1", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, c["id"])
    return c


async def test_stage_gating_blocks_costing_until_blocking_submitted(
        client, seed, ecr_template, departments, departments_member, session_factory):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    # Quality (C, stage1) submitting alone must NOT advance to stage 2; costing blocked.
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Quality"], "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400, res.text  # Tool Engineer (R) still pending
    # Submit Tool Engineer (R) -> stage 1 blocking done -> engine advances to stage 2 (APQP).
    # Observe advancement through the engine's read-through status (routing view uses
    # effective_status), not the raw assessment-row column which stays "pending".
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"}, headers=auth)
    routing = (await client.get(f"/api/v1/changes/{c['id']}/routing", headers=auth)).json()
    apqp = next(d for st in routing["stages"] for d in st["departments"]
                if d["department_id"] == departments["APQP"])
    # Spec §16 P1-2: the later stage stays dormant while in assessment.
    assert apqp["status"] == "pending"
    # Only the ASSESSMENT stage gates costing (rule book: later template
    # stages are lifecycle phases, summation and customer, not assessment
    # work). Entering costing wakes stage 2.
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
    routing = (await client.get(f"/api/v1/changes/{c['id']}/routing", headers=auth)).json()
    apqp = next(d for st in routing["stages"] for d in st["departments"]
                if d["department_id"] == departments["APQP"])
    assert apqp["status"] == "active"


async def test_deviation_requires_approval_then_clears(
        client, seed, ecr_template, departments, departments_member, session_factory):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1, "reason": "forgot MfgEng"}, headers=auth)
    assert res.status_code == 200, res.text
    routing = (await client.get(f"/api/v1/changes/{c['id']}/routing", headers=auth)).json()
    assert routing["deviation_status"] == "pending_approval"
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    for a in detail["assessments"]:
        if a["rasic_letter"] in ("R", "A"):
            await client.post(f"/api/v1/changes/{c['id']}/assessments",
                              json={"department_id": a["department_id"], "verdict": "feasible"}, headers=auth)
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Manufacturing Engineer"], "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400
    admin_auth = await _login_admin(client)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve", headers=admin_auth)
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text


async def test_apply_deviation_service(session_factory, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    cid = await _seeded_change(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"]); await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        r = await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=departments["Manufacturing Engineer"], rasic_letter="R", stage_order=1, reason="test add")
        await s.commit()
        assert r.deviation_status == "pending_approval" and r.has_deviation is True
        rows = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == departments["Manufacturing Engineer"])))).scalars().all()
        assert len(rows) == 1 and rows[0].rasic_letter == "R"
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        # admin (different user) approves — proposer was engineer (the lead), so engineer cannot self-approve
        r = await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"]); await s.commit()
        assert r.deviation_status == "approved"


async def test_apply_deviation_add_to_active_stage_stamps_due_date(
        session_factory, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeAssessment
    cid = await _seeded_change(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"]); await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        # stage_order=1 is the currently-active stage, so the new row must land "active".
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=departments["Manufacturing Engineer"], rasic_letter="R", stage_order=1, reason="test add")
        await s.commit()
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == cid)
            & (ChangeAssessment.department_id == departments["Manufacturing Engineer"])))).scalar_one()
        assert row.status == "active"
        assert row.due_date is not None


@pytest.mark.asyncio
async def test_promotion_bumps_template_and_repoints_standard(
        session_factory, seed, ecr_template, departments):
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest, ChangeRoutingStandard
    from app.models.workflow import WfTemplate, WfTemplateHistory, WfStage, WfStep, WfStepRasic
    cid = await _seeded_change(session_factory, seed)
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"])
        await ChangeRoutingService.apply_deviation(
            s, change, seed["engineer_id"], op="add",
            department_id=departments["Manufacturing Engineer"], rasic_letter="R", stage_order=1, reason="test add")
        await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"])
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.promote_to_standard(s, change, seed["admin_id"]); await s.commit()
    async with session_factory() as s:
        std = (await s.execute(select(ChangeRoutingStandard).where(
            ChangeRoutingStandard.change_type == "physical_part"))).scalar_one()
        tmpl = await s.get(WfTemplate, std.template_id)
        assert tmpl.version == 2 and std.template_version == 2
        hist = (await s.execute(select(WfTemplateHistory).where(
            WfTemplateHistory.template_id == tmpl.id))).scalars().all()
        assert any("CR-" in (h.change_note or "") for h in hist)
        # new structure includes Manufacturing Engineer
        stages = (await s.execute(select(WfStage).where(WfStage.template_id == tmpl.id))).scalars().all()
        dep_ids = set()
        for stg in stages:
            steps = (await s.execute(select(WfStep).where(WfStep.stage_id == stg.id))).scalars().all()
            for stp in steps:
                ras = (await s.execute(select(WfStepRasic).where(WfStepRasic.step_id == stp.id))).scalars().all()
                dep_ids |= {r.department_id for r in ras}
        assert departments["Manufacturing Engineer"] in dep_ids


@pytest.mark.asyncio
async def test_my_tasks_only_active_stage(client, seed, ecr_template, departments,
                                          session_factory):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    # engineer is not a member of any department in this seed, so expect 0;
    # this asserts the endpoint runs and filters by active status without error.
    assert isinstance(tasks, list)


@pytest.mark.asyncio
async def test_my_tasks_active_stage_filter_exercised(
        client, session_factory, seed, ecr_template, departments):
    """Engineer is a member of an active-stage dept (Tool Engineer, stage 1) and a
    pending-stage dept (APQP, stage 2). My-tasks must surface only the active one,
    then flip to APQP once stage 1's blocking submit advances the change to stage 2."""
    from app.models.workflow import UserDepartment
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=departments["Tool Engineer"]))
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=departments["APQP"]))
        await s.commit()
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)

    dep_ids = {t["department_id"] for t in (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()}
    assert departments["Tool Engineer"] in dep_ids   # active stage 1
    assert departments["APQP"] not in dep_ids         # stage 2 still pending → hidden

    # Submitting Tool Engineer (R) clears stage 1's blocking → stage 2 activates.
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"}, headers=auth)
    dep_ids2 = {t["department_id"] for t in (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
                if t["kind"] == "assessment"}
    # Spec §16 P1-2: stage 2 stays dormant during assessment and is no
    # assessment work anyway.
    assert departments["APQP"] not in dep_ids2
    assert departments["Tool Engineer"] not in dep_ids2  # submitted → verdict no longer pending


async def test_not_feasible_blocks_costing_until_justified(
        client, seed, departments, departments_member, session_factory):
    auth = await _login(client)
    # no ecr_template fixture here -> fallback single-stage all-R routing
    body = {"project_id": seed["project_id"], "title": "NF", "change_type": "physical_part",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-NF",
         "name": "ART-NF", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, c["id"])
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    # submit all assessments, one as not_feasible
    assessments = detail["assessments"]
    assert assessments, "fallback should create assessments"
    for i, a in enumerate(assessments):
        verdict = "not_feasible" if i == 0 else "feasible"
        await client.post(f"/api/v1/changes/{c['id']}/assessments",
                          json={"department_id": a["department_id"], "verdict": verdict}, headers=auth)
    # costing soft-blocked due to not_feasible
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400, res.text
    # overridable only via an approved transition deviation (4-eyes)
    admin_auth = await _login_admin(client)
    dev = (await client.post(f"/api/v1/changes/{c['id']}/deviations",
                             json={"to_status": "costing", "reason": "risk accepted"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/deviations/{dev['id']}/decide",
                      json={"decision": "approved"}, headers=admin_auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text


@pytest_asyncio.fixture
async def ecr_template_3stage(session_factory, departments):
    """stage1 Tool Engineer(R); stage2 Quality(C) ONLY (no blocking); stage3 APQP(A)."""
    from app.models.workflow import WfTemplate, WfStage, WfStep, WfStepRasic
    from app.models.change import ChangeRoutingStandard
    async with session_factory() as s:
        t = WfTemplate(name="ECR3", description="3-stage", version=1, is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [(1, [("Tool Engineer", "R")]), (2, [("Quality", "C")]), (3, [("APQP", "A")])]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"S{order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=departments[name], rasic_letter=letter))
        # map a DIFFERENT change_type so it doesn't clash with the ecr_template fixture's physical_part
        s.add(ChangeRoutingStandard(change_type="tooling", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
        return t.id


async def test_maybe_advance_cascades_through_optional_only_stage(
        client, seed, ecr_template_3stage, departments, departments_member, session_factory):
    auth = await _login(client)
    body = {"project_id": seed["project_id"], "title": "casc", "change_type": "tooling",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-C1",
         "name": "ART-C1", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, c["id"])
    # submit stage1 Tool Engineer (R) -> the engine advances, cascading THROUGH the
    # C-only stage 2 (no gate to wait on) and activating stage 3 APQP. Observe via
    # the routing view (effective_status), since raw assessment rows stay "pending".
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"}, headers=auth)
    # Spec §16 P1-2: the cascade runs when costing wakes the later stages.
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
    routing = (await client.get(f"/api/v1/changes/{c['id']}/routing", headers=auth)).json()
    by_dep = {d["department_id"]: d for st in routing["stages"] for d in st["departments"]}
    assert by_dep[departments["APQP"]]["status"] == "active"    # cascaded through stage 2 to stage 3
    assert by_dep[departments["Quality"]]["status"] == "active"  # C task in the skipped stage created (noted -> effective active)


@pytest_asyncio.fixture
async def ecr_template_multistage_dept(session_factory, departments):
    """Same dept appears in >1 stage: stage1 Tool Engineer(R) + Quality(R);
    stage2 Tool Engineer(A) + APQP(C). Mapped to change_type 'packaging'."""
    from app.models.workflow import WfTemplate, WfStage, WfStep, WfStepRasic
    from app.models.change import ChangeRoutingStandard
    async with session_factory() as s:
        t = WfTemplate(name="ECRmulti", description="multi-stage dept", version=1,
                       is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [
            (1, [("Tool Engineer", "R"), ("Quality", "R")]),
            (2, [("Tool Engineer", "A"), ("APQP", "C")]),
        ]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"S{order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=departments[name], rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="packaging", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
        return t.id


async def test_submit_assessment_targets_active_stage_row_for_multistage_dept(
        session_factory, seed, ecr_template_multistage_dept, departments, departments_member):
    """A department with rows in multiple stages must not raise MultipleResultsFound.
    submit_assessment targets the currently-active stage row, leaves later-stage rows
    untouched, and after all stage-1 blocking rows submit the same dept's stage-2 row
    becomes the next submit target."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    from app.models.change import ChangeRequest, ChangeAssessment
    cid = await _seeded_change(session_factory, seed, change_type="packaging")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"])
        await s.commit()

    te = departments["Tool Engineer"]

    def rows_by(rows):
        return {(a.department_id, a.stage_order): a for a in rows}

    # First submit for Tool Engineer must hit the stage-1 active row (not raise).
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(s, change, te, "feasible", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        rows = rows_by((await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all())
        # Execution state reads through the linked engine task: the stage-1 R task
        # is completed (effective "submitted"); the stage-2 row is untouched.
        assert rows[(te, 1)].effective_status == "submitted"   # stage-1 row taken
        assert rows[(te, 2)].effective_status == "pending"     # stage-2 row untouched

    # Finish stage-1 blocking (Quality R) -> stage 2 activates, incl. Tool Engineer(A).
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(
            s, change, departments["Quality"], "feasible", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        rows = rows_by((await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all())
        assert rows[(te, 2)].effective_status == "active"   # stage 2 now active (linked task)

    # Second submit for the SAME dept now targets the stage-2 row.
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(s, change, te, "feasible", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        rows = rows_by((await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all())
        assert rows[(te, 1)].effective_status == "submitted"
        assert rows[(te, 2)].effective_status == "submitted"


async def test_routing_view_reports_per_stage_status_for_multistage_dept(
        client, session_factory, seed, ecr_template_multistage_dept, departments):
    """GET /routing must key assessments by (department, stage): a department
    appearing in multiple stages shows its stage-1 row active while its
    stage-2 row is still pending — not one status echoed across all stages."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.models.change import ChangeRequest
    cid = await _seeded_change(session_factory, seed, change_type="packaging")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeRoutingService.build_routing(s, change, seed["engineer_id"])
        await s.commit()

    auth = await _login(client)
    res = await client.get(f"/api/v1/changes/{cid}/routing", headers=auth)
    assert res.status_code == 200, res.text
    te = departments["Tool Engineer"]
    by_stage = {}
    for st in res.json()["stages"]:
        for d in st["departments"]:
            if d["department_id"] == te:
                by_stage[st["stage_order"]] = d
    assert by_stage[1]["status"] == "active"
    assert by_stage[2]["status"] == "pending"
    assert by_stage[1]["assessment_id"] != by_stage[2]["assessment_id"]


async def test_deviation_add_requires_and_records_reason(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Adding a department mid-assessment is an audit event: no reason, no add;
    with one, the routing view shows who proposed it and why."""
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1}, headers=auth)
    assert res.status_code in (400, 422), res.text
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1,
        "reason": "Forgot MfgEng: the cell layout changes"}, headers=auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["deviation_status"] == "pending_approval"
    assert body["deviation_note"] == "Forgot MfgEng: the cell layout changes"
    assert body["deviation_proposed_by"] == seed["engineer_id"]


async def test_reject_deviation_undoes_the_added_department(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Rejecting a pending 'add' removes the row and its engine task again, so
    the department is off the hook and costing is no longer blocked by it."""
    from app.models.change import ChangeAssessment, ChangeChangelog
    from app.models.workflow import WfInstanceTask
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1, "reason": "maybe"}, headers=auth)
    assert res.status_code == 200, res.text
    # Proposer cannot reject their own deviation either (4-eyes both ways).
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "no"}, headers=auth)
    assert res.status_code == 400, res.text
    admin_auth = await _login_admin(client)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "MfgEng is not touched by this"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["deviation_status"] == "rejected"
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == c["id"])
            & (ChangeAssessment.department_id == departments["Manufacturing Engineer"])))).scalars().all()
        assert rows == []
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.department_id == departments["Manufacturing Engineer"]))).scalars().all()
        assert tasks == []
        log = (await s.execute(select(ChangeChangelog).where(
            (ChangeChangelog.change_id == c["id"])
            & (ChangeChangelog.action == "routing_deviation_rejected")))).scalars().all()
        assert len(log) == 1 and "not touched" in log[0].action_description
    # The standard rows alone now carry the change to costing.
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    for a in detail["assessments"]:
        if a["rasic_letter"] in ("R", "A"):
            await client.post(f"/api/v1/changes/{c['id']}/assessments",
                              json={"department_id": a["department_id"], "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text


async def test_reject_deviation_keeps_a_submitted_added_row(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """An added department that already answered is not silently erased by a
    late rejection: the answer stays, the deviation is closed as rejected."""
    from app.models.change import ChangeAssessment
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1, "reason": "maybe"}, headers=auth)
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Manufacturing Engineer"], "verdict": "feasible"}, headers=auth)
    admin_auth = await _login_admin(client)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "too late"}, headers=admin_auth)
    assert res.status_code == 400, res.text
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == c["id"])
            & (ChangeAssessment.department_id == departments["Manufacturing Engineer"])))).scalar_one()
        assert row.verdict == "feasible"


async def test_lead_with_pending_routing_deviation_gets_decision_action(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Someone else added a department mid-assessment: the change lead gets the
    decision on their plate, the proposer does not."""
    eng_auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, eng_auth, seed, session_factory)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1, "reason": "forgot"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    out = await client.get(f"/api/v1/changes/{c['id']}/my-actions", headers=eng_auth)
    kinds = [a["kind"] for a in out.json()["actions"]]
    assert "routing_deviation_decision" in kinds
    out = await client.get(f"/api/v1/changes/{c['id']}/my-actions", headers=admin_auth)
    kinds = [a["kind"] for a in out.json()["actions"]]
    assert "routing_deviation_decision" not in kinds


async def test_recommended_departments_include_consulted_with_their_letter(
        client, seed, ecr_template, departments, departments_member, session_factory):
    auth = await _login(client)
    body = {"project_id": seed["project_id"], "title": "Wall +0.2", "change_type": "physical_part",
            "reason": "sink", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    res = await client.get(f"/api/v1/changes/{c['id']}/recommended-departments", headers=auth)
    assert res.status_code == 200, res.text
    by_id = {r["id"]: r["rasic_letter"] for r in res.json()}
    assert by_id[departments["Tool Engineer"]] == "R"
    assert by_id[departments["Quality"]] == "C"   # consulted, but offered with its letter


async def test_reject_restores_a_relettered_department(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """"Not our responsibility" is a reletter to C; the lead's rejection puts
    the department back on the hook with the letter the routing gave it."""
    from app.models.change import ChangeAssessment
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    te = departments["Tool Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "reletter", "department_id": te, "rasic_letter": "C",
        "reason": "Not our responsibility: no tool change"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"], ChangeAssessment.department_id == te,
            ChangeAssessment.stage_order == 1))).scalar_one()
        # Spec §16 P1-3: the letter holds until the lead decides.
        assert row.rasic_letter == "R" and row.pending_rasic_letter == "C"
    admin_auth = await _login_admin(client)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "It is yours: the insert moves"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"], ChangeAssessment.department_id == te,
            ChangeAssessment.stage_order == 1))).scalar_one()
        assert row.rasic_letter == "R" and row.pending_rasic_letter is None
        assert row.task is None or row.task.is_actionable


async def test_informed_deviation_adds_no_row_no_gate_and_is_undone_on_reject(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """RASIC I: the department is told (a notification), gets no assessment
    row and no task, and no gate waits on it. A rejection takes it off."""
    from app.models.change import ChangeAssessment
    from app.models.notification import Notification
    from app.models.workflow import UserDepartment
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg = departments["Manufacturing Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "I", "stage_order": 1,
        "reason": "MfgEng should know"}, headers=auth)
    assert res.status_code == 200, res.text
    deps = {d["department_id"]: d for st in res.json()["stages"] for d in st["departments"]
            if st["stage_order"] == 1}
    assert deps[mfg]["rasic_letter"] == "I" and deps[mfg]["tier"] == "info"
    assert deps[mfg]["assessment_id"] is None
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            (ChangeAssessment.change_id == c["id"])
            & (ChangeAssessment.department_id == mfg)))).scalars().all()
        assert rows == []
        notes = (await s.execute(select(Notification).where(
            Notification.title.like("For your information%")))).scalars().all()
        assert notes, "the informed department is notified"
    # Nobody's my-tasks carry it.
    mine = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    assert not any(t.get("department_id") == mfg for t in mine
                   if t.get("change_id") == c["id"])
    # The stage-state never waits on it.
    st = (await client.get(f"/api/v1/changes/{c['id']}/stage-state", headers=auth))
    if st.status_code == 200:
        body = st.json()
        waiting = (body.get("assessment") or {}).get("waiting_on") or []
        assert all(w["department_id"] != mfg for w in waiting)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "not needed"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    ids = {d["department_id"] for st in res.json()["stages"] for d in st["departments"]}
    assert mfg not in ids


async def test_informed_deviation_approved_does_not_block_costing(
        client, seed, ecr_template, departments, departments_member, session_factory):
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg = departments["Manufacturing Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "I", "stage_order": 1,
        "reason": "FYI"}, headers=auth)
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    dep = next(d for st in res.json()["stages"] for d in st["departments"]
               if d["department_id"] == mfg)
    assert dep["rasic_letter"] == "I"
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    for a in detail["assessments"]:
        if a["rasic_letter"] in ("R", "A"):
            await client.post(f"/api/v1/changes/{c['id']}/assessments",
                              json={"department_id": a["department_id"], "verdict": "feasible"},
                              headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text


async def test_routing_shows_the_approved_letter_after_a_decline(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Item 7: after an approved re-letter the routing read returns the row's
    current letter, not the snapshot's original one."""
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    te = departments["Tool Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "reletter", "department_id": te, "rasic_letter": "C", "stage_order": 1,
        "reason": "not ours"}, headers=auth)
    assert res.status_code == 200, res.text
    dep = next(d for st in res.json()["stages"] for d in st["departments"]
               if d["department_id"] == te and st["stage_order"] == 1)
    assert dep["rasic_letter"] == "R" and dep["pending_rasic_letter"] == "C"
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    dep = next(d for st in res.json()["stages"] for d in st["departments"]
               if d["department_id"] == te and st["stage_order"] == 1)
    assert dep["rasic_letter"] == "C" and dep["tier"] == "optional"
    assert dep["pending_rasic_letter"] is None


async def test_deviation_added_row_outside_snapshot_is_on_the_routing(
        client, seed, ecr_template, departments, departments_member, session_factory):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg = departments["Manufacturing Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 1,
        "reason": "forgot"}, headers=auth)
    assert res.status_code == 200, res.text
    dep = next(d for st in res.json()["stages"] for d in st["departments"]
               if d["department_id"] == mfg)
    assert dep["rasic_letter"] == "R" and dep["assessment_id"] is not None


# --- Review findings on aee06c57 -------------------------------------------

async def test_add_on_an_existing_row_is_refused_not_relettered(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Finding 2: op add on a department that already has a row in the stage
    must not re-letter it (R -> I dropped the duty unapproved)."""
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstanceTask
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    te = departments["Tool Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": te, "rasic_letter": "I", "stage_order": 1,
        "reason": "x"}, headers=auth)
    assert res.status_code == 400
    assert "reletter" in res.json()["detail"]
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == te))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert row.rasic_letter == "R" and row.pending_rasic_letter is None
        assert (task.rasic_letter, task.status, task.is_actionable) == ("R", "active", True)


async def test_approved_reletter_to_informed_drops_the_row_and_its_task(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Finding 2: I has no row: an approved reletter to I removes the
    assessment row and its task; the department stays on the routing as I."""
    from app.models.change import ChangeAssessment, ChangeRouting
    from app.models.workflow import WfInstanceTask
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    q = departments["Quality"]   # C in stage 1
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == q))).scalar_one()
        task_id = row.wf_instance_task_id
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "reletter", "department_id": q, "rasic_letter": "I", "stage_order": 1,
        "reason": "just keep us posted"}, headers=auth)
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    dep = [d for st in res.json()["stages"] for d in st["departments"]
           if d["department_id"] == q]
    assert [(d["rasic_letter"], d["assessment_id"]) for d in dep] == [("I", None)]
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == q))).scalars().all()
        assert rows == []
        if task_id is not None:
            assert await s.get(WfInstanceTask, task_id) is None
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == c["id"]))).scalar_one()
        st1 = next(st for st in routing.standard_snapshot["stages"] if st["stage_order"] == 1)
        assert [d["rasic_letter"] for d in st1["departments"]
                if d["department_id"] == q] == ["I"]


async def test_later_stage_deviation_R_is_asked_when_its_stage_starts(
        client, seed, ecr_template_3stage, departments, departments_member, session_factory):
    """Finding 1: an R department a deviation added to a later, C-only stage
    gets its active task when that stage starts; the stage holds on it
    instead of cascading past it (and the row is never waived)."""
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    body = {"project_id": seed["project_id"], "title": "casc", "change_type": "tooling",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-C9",
         "name": "ART-C9", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, c["id"])
    mfg = departments["Manufacturing Engineer"]
    r = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 2,
        "reason": "needed"}, headers=auth)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                          headers=admin_auth)
    assert r.status_code == 200, r.text
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"},
                      headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == c["id"]))).scalar_one()
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert inst.current_stage_order == 2      # held on MFG, no cascade to 3
        assert (task.stage_order, task.status, task.is_actionable) == (2, "active", True)
        # One task only for the row (the repair did not add a second one).
        n = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.department_id == mfg))).scalars().all()
        assert len(n) == 1


async def test_deviation_rights_lead_pm_admin_or_the_department(
        client, seed, departments, session_factory):
    """Finding 2: POST /routing/deviation is the lead's, PM's, an admin's, or
    a member's of the department concerned (its own decline)."""
    from app.models.change import ChangeRequest
    from app.models.workflow import UserDepartment, WfTemplate, WfStage, WfStep, WfStepRasic
    admin_auth = await _login_admin(client)
    async with session_factory() as s:
        t = WfTemplate(name="ECRx", description="x", version=1, is_active=True, created_by=1)
        s.add(t); await s.flush()
        st = WfStage(template_id=t.id, stage_order=1, name="S1"); s.add(st); await s.flush()
        sp = WfStep(stage_id=st.id, step_name="S1", position_in_stage=1); s.add(sp); await s.flush()
        s.add(WfStepRasic(step_id=sp.id, department_id=departments["Tool Engineer"], rasic_letter="R"))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
    body = {"project_id": seed["project_id"], "title": "rights", "change_type": "physical_part",
            "reason": "r", "lead_id": seed["admin_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=admin_auth)).json()
    await approve_gates(client, admin_auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-RR",
         "name": "ART-RR", "part_type": "internal_mfg", "item_category": "article"},
         headers=admin_auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]},
                      headers=admin_auth)
    await advance_to_assessment(client, admin_auth, session_factory, c["id"])
    outsider = await _login(client)   # engineer: not lead, not PM, no membership
    te = departments["Tool Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "reletter", "department_id": te, "rasic_letter": "C", "reason": "not ours"},
        headers=outsider)
    assert res.status_code == 403, res.text
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=te))
        await s.commit()
    # A member may decline its own row ...
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "reletter", "department_id": te, "rasic_letter": "C", "reason": "not ours"},
        headers=outsider)
    assert res.status_code == 200, res.text
    # ... and right after, name who should take over ...
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Quality"], "rasic_letter": "R",
        "stage_order": 1, "reason": "not ours"}, headers=outsider)
    assert res.status_code == 200, res.text
    # ... but never remove another department.
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "remove", "department_id": departments["Quality"], "reason": "x"},
        headers=outsider)
    assert res.status_code == 403, res.text


async def test_informed_department_is_told_once_at_routing_start(
        session_factory, seed, departments):
    """Finding 10: a stage-1 I department gets the engine's FYI, not also
    the "entered assessment" broadcast."""
    from app.models.change import ChangeRequest
    from app.models.notification import Notification
    from app.models.workflow import UserDepartment
    from app.services.change_routing_service import ChangeRoutingService
    async with session_factory() as s:
        t = WfTemplate(name="ECRi", description="x", version=1, is_active=True, created_by=1)
        s.add(t); await s.flush()
        st = WfStage(template_id=t.id, stage_order=1, name="S1"); s.add(st); await s.flush()
        sp = WfStep(stage_id=st.id, step_name="S1", position_in_stage=1); s.add(sp); await s.flush()
        s.add(WfStepRasic(step_id=sp.id, department_id=departments["Tool Engineer"], rasic_letter="R"))
        s.add(WfStepRasic(step_id=sp.id, department_id=departments["Sales"], rasic_letter="I"))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=departments["Sales"]))
        c = ChangeRequest(change_number="CR-I-1", project_id=seed["project_id"], title="i",
                          change_type="physical_part", status="in_assessment",
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"])
        s.add(c); await s.flush()
        await ChangeRoutingService.build_routing(s, c, seed["admin_id"])
        await s.commit()
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"]))).scalars().all()
    titles = [n.title for n in notes]
    assert len(titles) == 1, titles
    assert titles[0].startswith("FYI")


async def test_promotion_keeps_one_role_per_department_and_stage(
        session_factory, seed, ecr_template, departments):
    """Finding 10: a department holding a row and an I entry on the snapshot
    in the same stage is promoted once (its row's letter), not as R and I."""
    from app.models.change import ChangeRequest, ChangeAssessment, ChangeRouting
    from app.models.workflow import WfStepRasic as R
    from app.services.change_routing_service import ChangeRoutingService
    sales = departments["Sales"]
    async with session_factory() as s:
        c = ChangeRequest(change_number="CR-P-1", project_id=seed["project_id"], title="p",
                          change_type="physical_part", status="released",
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"])
        s.add(c); await s.flush()
        s.add(ChangeRouting(
            change_id=c.id, template_id=ecr_template, template_version=1,
            deviation_status="approved", has_deviation=True,
            standard_snapshot={"stages": [
                {"stage_order": 1, "departments": [
                    {"department_id": departments["Tool Engineer"], "rasic_letter": "R"}]},
                {"stage_order": 2, "departments": [
                    {"department_id": departments["APQP"], "rasic_letter": "A"},
                    {"department_id": sales, "rasic_letter": "I"}]}]}))
        for dept, order, letter in ((departments["Tool Engineer"], 1, "R"),
                                    (departments["APQP"], 2, "A"), (sales, 2, "R")):
            s.add(ChangeAssessment(change_id=c.id, department_id=dept, verdict="feasible",
                                   stage_order=order, rasic_letter=letter, status="submitted"))
        await s.flush()
        await ChangeRoutingService.promote_to_standard(s, c, seed["admin_id"])
        await s.commit()
        rows = (await s.execute(
            select(R.department_id, R.rasic_letter, WfStage.stage_order)
            .join(WfStep, WfStep.id == R.step_id)
            .join(WfStage, WfStage.id == WfStep.stage_id)
            .where(WfStage.template_id == ecr_template))).all()
    sales_roles = [(o, l) for d, l, o in rows if d == sales]
    assert sales_roles == [(2, "R")]


async def test_routing_sweep_is_a_dry_run_by_default_and_idempotent(
        client, seed, ecr_template, departments, departments_member,
        session_factory, monkeypatch):
    """Finding 4: scripts/repair_routing_tasks.py rolls back without --apply,
    writes with it, and finds nothing the second time."""
    import scripts.repair_routing_tasks as sweep_mod
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstanceTask
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    te = departments["Tool Engineer"]
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == te))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        row.wf_instance_task_id = None
        await s.flush()
        await s.delete(task)
        await s.commit()
    monkeypatch.setattr(sweep_mod, "AsyncSessionLocal", session_factory)
    assert await sweep_mod.sweep(apply=False) == 1
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == te))).scalar_one()
        assert row.wf_instance_task_id is None          # dry run wrote nothing
    assert await sweep_mod.sweep(apply=True) == 1
    assert await sweep_mod.sweep(apply=True) == 0
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == te))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert task.status == "active" and task.rasic_letter == "R"


async def test_generic_task_complete_on_a_change_task_repairs_the_next_stage(
        client, seed, ecr_template_3stage, departments, departments_member, session_factory):
    """Finding 1: POST /workflow-instances/{id}/tasks/{tid}/complete on a
    change's task (instance locked, repair after): a row of the stage the
    engine started that no template/snapshot entry carries gets its active
    task with the stage, and the stage holds on it."""
    from app.models.change import ChangeAssessment, ChangeRequest
    from app.models.workflow import WfInstance, WfInstanceTask
    auth = await _login(client)
    body = {"project_id": seed["project_id"], "title": "gen", "change_type": "tooling",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-G1",
         "name": "ART-G1", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, c["id"])
    mfg = departments["Manufacturing Engineer"]
    async with session_factory() as s:
        # A later-stage row placed directly (no deviation), and the change
        # already past assessment so the engine may advance on complete.
        s.add(ChangeAssessment(change_id=c["id"], department_id=mfg, verdict="pending",
                               stage_order=2, rasic_letter="R", status="pending"))
        ch = await s.get(ChangeRequest, c["id"])
        ch.status = "costing"
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == c["id"]))).scalar_one()
        task = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.department_id == departments["Tool Engineer"]))).scalar_one()
        await s.commit()
        inst_id, task_id = inst.id, task.id
    res = await client.post(f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/complete",
                            json={"decision": "approved", "notes": "ok"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        inst = await s.get(WfInstance, inst_id)
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        assert inst.current_stage_order == 2
        t = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert (t.stage_order, t.status) == (2, "active")


# --- Review findings on 11a1e990 -------------------------------------------

async def _in_costing_at_stage2(client, auth, seed, session_factory, departments):
    """ecr_template change past assessment: Tool Engineer answered, the
    change in costing, the instance on stage 2 (APQP A active)."""
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"],
                            "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
    return c


async def _complete_apqp(client, auth, session_factory, cid, apqp):
    from app.models.workflow import WfInstance, WfInstanceTask
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == cid))).scalar_one()
        task = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.department_id == apqp))).scalar_one()
        inst_id, task_id = inst.id, task.id
    res = await client.post(f"/api/v1/workflow-instances/{inst_id}/tasks/{task_id}/complete",
                            json={"decision": "approved", "notes": "ok"}, headers=auth)
    assert res.status_code == 200, res.text
    return inst_id


async def test_late_row_stays_owed_after_the_instance_completes(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Finding 1: a department added to a passed stage stays on My Tasks,
    in the cockpit (Chase, with the stage to take it off) and in the
    costing -> quoting message, by name, after the instance completed."""
    from app.models.change import ChangeAssessment, ChangeRequest
    from app.models.workflow import WfInstance, WfInstanceTask
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    auth = await _login(client)
    c = await _in_costing_at_stage2(client, auth, seed, session_factory, departments)
    mfg = departments["Manufacturing Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 1,
        "reason": "forgotten"}, headers=auth)
    assert res.status_code == 200, res.text
    inst_id = await _complete_apqp(client, auth, session_factory, c["id"], departments["APQP"])
    async with session_factory() as s:
        inst = await s.get(WfInstance, inst_id)
        assert inst.status == "completed"
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert (task.status, task.step_id) == ("active", None)
        change = await ChangeService.get_change(s, c["id"])
        assert await ChangeRoutingService.blocking_waiting(s, change) == ["Manufacturing Engineer"]
        why = await ChangeService._guard(s, change, "quoting")
        assert "waiting on Manufacturing Engineer" in why
    mine = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    assert row.id in [t.get("assessment_id") for t in mine if t["kind"] == "assessment"]
    acts = (await client.get(f"/api/v1/changes/{c['id']}/my-actions",
                             headers=auth)).json()["actions"]
    late = [a for a in acts if a["kind"] == "late_assessment"]
    assert [(a["assessment_id"], a["stage_order"]) for a in late] == [(row.id, 1)]
    assert any(a["kind"] == "assessment" and a["assessment_id"] == row.id for a in acts)


async def test_add_after_the_instance_completed_gets_a_stepless_task(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Finding 1: no active instance (every stage passed) is no reason to
    leave an added R department without a task: it goes onto the completed
    instance, step-less and active, and is listed and waited on."""
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    auth = await _login(client)
    c = await _in_costing_at_stage2(client, auth, seed, session_factory, departments)
    inst_id = await _complete_apqp(client, auth, session_factory, c["id"], departments["APQP"])
    mfg = departments["Manufacturing Engineer"]
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 2,
        "reason": "late find"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert task.instance_id == inst_id
        assert (task.status, task.step_id, task.is_actionable) == ("active", None, True)
        assert (await s.get(WfInstance, inst_id)).status == "completed"
        change = await ChangeService.get_change(s, c["id"])
        assert await ChangeRoutingService.blocking_waiting(s, change) == ["Manufacturing Engineer"]
    mine = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    assert row.id in [t.get("assessment_id") for t in mine if t["kind"] == "assessment"]


async def test_stage_start_task_of_a_row_outside_template_and_snapshot_has_no_step(
        client, seed, ecr_template_3stage, departments, departments_member, session_factory):
    """Finding 2: the engine creates the task of a deviation-added later
    row with NO step (not the stage's first), so My Tasks lists it after the
    change left assessment, and the department is told with a link to the
    change's assessments."""
    from app.models.change import ChangeAssessment
    from app.models.notification import Notification
    from app.models.workflow import WfInstanceTask
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    body = {"project_id": seed["project_id"], "title": "stepless", "change_type": "tooling",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-SL",
         "name": "ART-SL", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, c["id"])
    mfg = departments["Manufacturing Engineer"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 2,
        "reason": "needed"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"},
                      headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert (task.stage_order, task.status, task.step_id) == (2, "active", None)
        links = (await s.execute(select(Notification.link).where(
            Notification.user_id == seed["engineer_id"],
            Notification.title.like("Assessment task:%")))).scalars().all()
    assert f"/changes/{c['id']}?tab=assessments" in links
    mine = (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()
    assert row.id in [t.get("assessment_id") for t in mine if t["kind"] == "assessment"]


async def test_approved_reletter_moves_the_snapshot_so_the_stage_starts_clean(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Finding 7: APQP (A, stage 2) declines to C before stage 2 starts;
    approved, the snapshot says C, so the stage starts with a C task for
    the row and no orphan A task."""
    from app.models.change import ChangeAssessment, ChangeRouting
    from app.models.workflow import WfInstance, WfInstanceTask
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    apqp = departments["APQP"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "reletter", "department_id": apqp, "rasic_letter": "C", "stage_order": 2,
        "reason": "not ours"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    async with session_factory() as s:
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == c["id"]))).scalar_one()
        st2 = next(st for st in routing.standard_snapshot["stages"] if st["stage_order"] == 2)
        assert [d["rasic_letter"] for d in st2["departments"]
                if d["department_id"] == apqp] == ["C"]
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"},
                      headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == c["id"]))).scalar_one()
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.department_id == apqp))).scalars().all()
        assert [(t.rasic_letter, t.status) for t in tasks] == [("C", "noted")]
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == apqp))).scalar_one()
        assert row.wf_instance_task_id == tasks[0].id


async def test_approved_reletter_to_informed_keeps_the_rows_documents(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Finding 4: the row goes, its documents stay on the change, unlinked."""
    from app.models.change import ChangeAssessment, ChangeAttachment
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    q = departments["Quality"]
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == q))).scalar_one()
        att = ChangeAttachment(change_id=c["id"], filename="q.pdf", stored_path="x/q.pdf",
                               content_type="application/pdf", size_bytes=1, sha256="0" * 64,
                               assessment_id=row.id, uploaded_by=seed["engineer_id"])
        s.add(att)
        await s.commit()
        att_id = att.id
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "reletter", "department_id": q, "rasic_letter": "I", "stage_order": 1,
        "reason": "keep us posted"}, headers=auth)).status_code == 200
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        att = await s.get(ChangeAttachment, att_id)
        assert att is not None and att.assessment_id is None
        assert (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == q))).scalars().all() == []


async def test_pending_decline_allows_one_R_or_A_add_in_its_stage(
        client, seed, departments, session_factory):
    """Finding 6: while its decline is pending, a department names ONE
    department to take over, as R or A, in the declined row's stage."""
    from app.models.workflow import UserDepartment
    admin_auth = await _login_admin(client)
    async with session_factory() as s:
        t = WfTemplate(name="ECRd", description="x", version=1, is_active=True, created_by=1)
        s.add(t); await s.flush()
        for order in (1, 2):
            st = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
            s.add(st); await s.flush()
            sp = WfStep(stage_id=st.id, step_name=f"S{order}", position_in_stage=1)
            s.add(sp); await s.flush()
            s.add(WfStepRasic(step_id=sp.id, rasic_letter="R" if order == 1 else "A",
                              department_id=departments["Tool Engineer" if order == 1 else "Sales"]))
        s.add(ChangeRoutingStandard(change_type="physical_part", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
    body = {"project_id": seed["project_id"], "title": "decl", "change_type": "physical_part",
            "reason": "r", "lead_id": seed["admin_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=admin_auth)).json()
    await approve_gates(client, admin_auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-DC",
         "name": "ART-DC", "part_type": "internal_mfg", "item_category": "article"},
         headers=admin_auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]},
                      headers=admin_auth)
    await advance_to_assessment(client, admin_auth, session_factory, c["id"])
    te = departments["Tool Engineer"]
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=te))
        await s.commit()
    member = await _login(client)
    url = f"/api/v1/changes/{c['id']}/routing/deviation"
    assert (await client.post(url, json={
        "op": "reletter", "department_id": te, "rasic_letter": "C", "reason": "not ours"},
        headers=member)).status_code == 200
    # Not R/A, or another stage: refused.
    res = await client.post(url, json={"op": "add", "department_id": departments["Quality"],
                                       "rasic_letter": "C", "stage_order": 1, "reason": "x"},
                            headers=member)
    assert res.status_code == 403, res.text
    res = await client.post(url, json={"op": "add", "department_id": departments["Quality"],
                                       "rasic_letter": "R", "stage_order": 2, "reason": "x"},
                            headers=member)
    assert res.status_code == 403, res.text
    # One R in the declined stage: allowed.
    res = await client.post(url, json={"op": "add", "department_id": departments["Quality"],
                                       "rasic_letter": "R", "reason": "theirs"},
                            headers=member)
    assert res.status_code == 200, res.text
    # A second one: refused.
    res = await client.post(url, json={"op": "add", "department_id": departments["APQP"],
                                       "rasic_letter": "A", "stage_order": 1, "reason": "x"},
                            headers=member)
    assert res.status_code == 403, res.text
    assert "one department" in res.json()["detail"]


async def test_sweep_lists_late_rows_even_when_the_repair_completes_the_instance(
        client, seed, ecr_template, departments, departments_member,
        session_factory, monkeypatch, capsys):
    """Findings 3 and 9: the dry run prints each late row on its own line,
    also when the repair's advance completes the instance; only a row in
    neither the snapshot nor the template is flagged late."""
    import scripts.repair_routing_tasks as sweep_mod
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    auth = await _login(client)
    c = await _in_costing_at_stage2(client, auth, seed, session_factory, departments)
    mfg = departments["Manufacturing Engineer"]
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == c["id"]))).scalar_one()
        # APQP's stage-2 task answered: the repair's advance re-check then
        # completes the instance.
        apqp_task = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.department_id == departments["APQP"]))).scalar_one()
        apqp_task.status = "approved"
        # A true deviation add of stage 1, never given its task.
        s.add(ChangeAssessment(change_id=c["id"], department_id=mfg, verdict="pending",
                               stage_order=1, rasic_letter="R", status="pending"))
        await s.commit()
    monkeypatch.setattr(sweep_mod, "AsyncSessionLocal", session_factory)
    capsys.readouterr()
    assert await sweep_mod.sweep(apply=False) == 1
    out = capsys.readouterr().out
    late_lines = [ln for ln in out.splitlines() if "LATE" in ln]
    assert len(late_lines) == 1 and "Manufacturing Engineer R stage 1" in late_lines[0]
    assert await sweep_mod.sweep(apply=True) == 1
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == c["id"]))).scalar_one()
        assert inst.status == "completed"
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert (task.status, task.step_id) == ("active", None)


async def _snap_entries(session_factory, cid, dept_id):
    from app.models.change import ChangeRouting
    async with session_factory() as s:
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == cid))).scalar_one()
        return [(st["stage_order"], d) for st in routing.standard_snapshot["stages"]
                for d in st["departments"] if d["department_id"] == dept_id]


async def test_rejecting_a_later_deviation_keeps_an_earlier_approved_add(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """An approved add is written into the routing snapshot (marked
    added_by_deviation), so rejecting a different, later deviation undoes
    only that one: the approved department keeps its row and its task."""
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstanceTask
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg, sales = departments["Manufacturing Engineer"], departments["Sales"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 1,
        "reason": "forgot MfgEng"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    assert await _snap_entries(session_factory, c["id"], mfg) == [
        (1, {"department_id": mfg, "rasic_letter": "R", "added_by_deviation": True})]
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        task_id = row.wf_instance_task_id
        task = await s.get(WfInstanceTask, task_id)
        assert (task.status, task.step_id) == ("active", None)
    # A second deviation, rejected: only Sales comes off again.
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": sales, "rasic_letter": "R", "stage_order": 1,
        "reason": "maybe Sales"}, headers=auth)).status_code == 200
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "Sales not touched"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        assert (row.rasic_letter, row.wf_instance_task_id) == ("R", task_id)
        task = await s.get(WfInstanceTask, task_id)
        assert (task.status, task.step_id) == ("active", None)
        assert (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == sales))).scalars().all() == []
    assert len(await _snap_entries(session_factory, c["id"], mfg)) == 1
    # The approved add still holds costing until it answers.
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"],
                            "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400, res.text


async def test_stage_start_after_an_approved_add_creates_one_stepless_task(
        client, seed, ecr_template_3stage, departments, departments_member, session_factory):
    """An approved add of a later stage is on the snapshot but still outside
    the template: when its stage starts, it gets exactly one task, without a
    step, also after a later deviation was rejected in between."""
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    body = {"project_id": seed["project_id"], "title": "approved add", "change_type": "tooling",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-AA",
         "name": "ART-AA", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, c["id"])
    mfg, sales = departments["Manufacturing Engineer"], departments["Sales"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 2,
        "reason": "needed"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    assert (2, {"department_id": mfg, "rasic_letter": "R", "added_by_deviation": True}) \
        in await _snap_entries(session_factory, c["id"], mfg)
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": sales, "rasic_letter": "R", "stage_order": 2,
        "reason": "maybe"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                              json={"reason": "no"}, headers=admin_auth)).status_code == 200
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"},
                      headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == c["id"]))).scalar_one()
        assert inst.current_stage_order == 2          # held on the added R
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.department_id == mfg))).scalars().all()
        assert [(t.stage_order, t.status, t.step_id) for t in tasks] == [(2, "active", None)]
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        assert row.wf_instance_task_id == tasks[0].id
        assert (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.department_id == sales))).scalars().all() == []


async def test_sweep_does_not_waive_an_approved_add_of_a_passed_stage(
        client, seed, ecr_template, departments, departments_member,
        session_factory, monkeypatch):
    """An approved add sits on the snapshot, but the sweep still treats it as
    a deviation add: missing its task on a passed stage, it is flagged late
    (active, no step), never waived as a standard row."""
    import scripts.repair_routing_tasks as sweep_mod
    from app.models.change import ChangeAssessment
    from app.models.workflow import WfInstance, WfInstanceTask
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg = departments["Manufacturing Engineer"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 1,
        "reason": "needed"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    # History: the row lost its task and the instance moved past stage 1.
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        row.wf_instance_task_id = None
        await s.flush()
        await s.delete(task)
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == c["id"]))).scalar_one()
        inst.current_stage_order = 2
        await s.commit()
    monkeypatch.setattr(sweep_mod, "AsyncSessionLocal", session_factory)
    assert await sweep_mod.sweep(apply=True) >= 1
    async with session_factory() as s:
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == c["id"],
            ChangeAssessment.department_id == mfg))).scalar_one()
        task = await s.get(WfInstanceTask, row.wf_instance_task_id)
        assert (task.status, task.step_id, task.is_actionable) == ("active", None, True)
        assert "after it had passed" in (task.notes or "")


async def test_approved_remove_drops_the_department_from_the_snapshot(
        client, seed, ecr_template, departments, departments_member, session_factory):
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    apqp = departments["APQP"]
    assert await _snap_entries(session_factory, c["id"], apqp) == [
        (2, {"department_id": apqp, "rasic_letter": "A"})]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "remove", "department_id": apqp, "stage_order": 2,
        "reason": "not involved"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    assert await _snap_entries(session_factory, c["id"], apqp) == []


# ---- adds approved before approvals wrote the snapshot; pending removals ----

async def _strip_snapshot_entry(session_factory, cid, dept_id):
    """History: the add was approved before approve_deviation wrote approved
    adds into the snapshot (commit 9d5ee708), so it has no entry there."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.change import ChangeRouting
    async with session_factory() as s:
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == cid))).scalar_one()
        snap = dict(routing.standard_snapshot)
        snap["stages"] = [{**st, "departments": [d for d in st["departments"]
                                                  if d["department_id"] != dept_id]}
                          for st in snap["stages"]]
        routing.standard_snapshot = snap
        flag_modified(routing, "standard_snapshot")
        await s.commit()


async def _deviation_entries(session_factory, cid):
    from app.models.change import ChangeChangelog
    async with session_factory() as s:
        return (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "routing_deviation")
            .order_by(ChangeChangelog.id))).scalars().all()


async def _rows_of(session_factory, cid, dept_id):
    from app.models.change import ChangeAssessment
    async with session_factory() as s:
        return (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == dept_id))).scalars().all()


async def test_reject_keeps_an_add_approved_before_the_snapshot_kept_adds(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """An add approved before approvals wrote the snapshot is outside it. A
    rejection of a later deviation removes only the rows ITS records asked
    for, so the earlier add stays (even when its own entry carries no record
    at all)."""
    from app.models.change import ChangeChangelog
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg, sales = departments["Manufacturing Engineer"], departments["Sales"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 1,
        "reason": "forgot MfgEng"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    await _strip_snapshot_entry(session_factory, c["id"], mfg)
    # Its entry predates the records, and not even the text is readable.
    (entry,) = await _deviation_entries(session_factory, c["id"])
    async with session_factory() as s:
        e = await s.get(ChangeChangelog, entry.id)
        e.new_value = None
        e.action_description = "Routing deviation: legacy"
        await s.commit()
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": sales, "rasic_letter": "R", "stage_order": 1,
        "reason": "maybe Sales"}, headers=auth)).status_code == 200
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "Sales not touched"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    (row,) = await _rows_of(session_factory, c["id"], mfg)
    assert row.rasic_letter == "R" and row.wf_instance_task_id is not None
    assert await _rows_of(session_factory, c["id"], sales) == []


async def test_reject_without_records_keeps_rows_of_approved_deviations(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """A pending deviation older than the records falls back to the
    snapshot, but never removes a row an approved deviation entry names
    (department and stage, read from the older description)."""
    from app.models.change import ChangeChangelog
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg, sales = departments["Manufacturing Engineer"], departments["Sales"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 1,
        "reason": "forgot MfgEng"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    await _strip_snapshot_entry(session_factory, c["id"], mfg)
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": sales, "rasic_letter": "R", "stage_order": 1,
        "reason": "maybe Sales"}, headers=auth)).status_code == 200
    # Both entries as they were written before the records existed.
    async with session_factory() as s:
        for entry in await _deviation_entries(session_factory, c["id"]):
            e = await s.get(ChangeChangelog, entry.id)
            e.new_value = None
            assert "added dept" in e.action_description
        await s.commit()
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "Sales not touched"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert len(await _rows_of(session_factory, c["id"], mfg)) == 1
    assert await _rows_of(session_factory, c["id"], sales) == []


async def test_sweep_backfills_snapshot_entries_of_approved_adds(
        client, seed, ecr_template, departments, departments_member,
        session_factory, monkeypatch):
    """scripts/repair_routing_tasks.py writes a snapshot entry
    (added_by_deviation) for a row an approved deviation added before
    approvals did so: never while a deviation is pending (the rejection's
    own fallback keeps the approved row meanwhile), not in a dry run, once
    with --apply."""
    import scripts.repair_routing_tasks as sweep_mod
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg, sales = departments["Manufacturing Engineer"], departments["Sales"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 1,
        "reason": "forgot MfgEng"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    await _strip_snapshot_entry(session_factory, c["id"], mfg)
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": sales, "rasic_letter": "R", "stage_order": 1,
        "reason": "maybe Sales"}, headers=auth)).status_code == 200
    monkeypatch.setattr(sweep_mod, "AsyncSessionLocal", session_factory)
    # A deviation is pending: the change is skipped.
    assert await sweep_mod.backfill_snapshots(True, [c["id"]]) == 0
    assert await _snap_entries(session_factory, c["id"], mfg) == []
    # The rejection keeps the approved add all the same.
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "no"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert len(await _rows_of(session_factory, c["id"], mfg)) == 1
    assert await _rows_of(session_factory, c["id"], sales) == []
    # Decided: now it is backfilled.
    assert await sweep_mod.backfill_snapshots(False, [c["id"]]) == 1
    assert await _snap_entries(session_factory, c["id"], mfg) == []
    await sweep_mod.sweep(apply=True)
    assert await _snap_entries(session_factory, c["id"], mfg) == [
        (1, {"department_id": mfg, "rasic_letter": "R", "added_by_deviation": True})]
    assert [o for o, _ in await _snap_entries(session_factory, c["id"], sales)] \
        == [2]                                   # the template's I, nothing more
    assert await sweep_mod.backfill_snapshots(True, [c["id"]]) == 0


async def _add_remove_readd(client, auth, admin_auth, session_factory, cid, dept):
    """An add approved before approvals wrote the snapshot, its approved
    removal, and a new add of the same department and stage, pending."""
    url = f"/api/v1/changes/{cid}/routing/deviation"
    assert (await client.post(url, json={"op": "add", "department_id": dept,
        "rasic_letter": "R", "stage_order": 1, "reason": "x"}, headers=auth)).status_code == 200
    assert (await client.post(url + "/approve", headers=admin_auth)).status_code == 200
    await _strip_snapshot_entry(session_factory, cid, dept)
    assert (await client.post(url, json={"op": "remove", "department_id": dept,
        "stage_order": 1, "reason": "y"}, headers=auth)).status_code == 200
    assert (await client.post(url + "/approve", headers=admin_auth)).status_code == 200
    assert await _rows_of(session_factory, cid, dept) == []
    assert (await client.post(url, json={"op": "add", "department_id": dept,
        "rasic_letter": "R", "stage_order": 1, "reason": "z"}, headers=auth)).status_code == 200
    assert len(await _rows_of(session_factory, cid, dept)) == 1


async def test_backfill_never_promotes_a_pending_readd(
        client, seed, ecr_template, departments, departments_member,
        session_factory, monkeypatch):
    """Added (approved), taken off (approved), added again (pending): the
    sweep must not take the pending re-add for the first approval, so the
    rejection still takes it off."""
    import scripts.repair_routing_tasks as sweep_mod
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg = departments["Manufacturing Engineer"]
    await _add_remove_readd(client, auth, admin_auth, session_factory, c["id"], mfg)
    monkeypatch.setattr(sweep_mod, "AsyncSessionLocal", session_factory)
    assert await sweep_mod.backfill_snapshots(True, [c["id"]]) == 0
    assert await _snap_entries(session_factory, c["id"], mfg) == []
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "no"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert await _rows_of(session_factory, c["id"], mfg) == []


async def _to_legacy_text(session_factory, cid):
    """Every deviation entry as written before records existed: no
    new_value, the op only in the description (prod data at deploy)."""
    from app.models.change import ChangeChangelog
    async with session_factory() as s:
        for entry in await _deviation_entries(session_factory, cid):
            e = await s.get(ChangeChangelog, entry.id)
            rec = json.loads(e.new_value)
            e.new_value = None
            if rec["op"] == "add":
                e.action_description = (f"Routing deviation: added dept {rec['department_id']} "
                                        f"as {rec['rasic_letter']} in stage {rec['stage_order']}")
            elif rec["op"] == "remove":
                e.action_description = f"Routing deviation: removed dept {rec['department_id']}"
        await s.commit()


async def test_legacy_reject_replays_the_approved_history_in_order(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Old-format changelog text only: an add approved, then removed, then
    asked again by the pending deviation. The first approval no longer
    protects the re-add (the approved removal released it), so the
    rejection takes it off."""
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg = departments["Manufacturing Engineer"]
    await _add_remove_readd(client, auth, admin_auth, session_factory, c["id"], mfg)
    await _to_legacy_text(session_factory, c["id"])
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/reject",
                            json={"reason": "no"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert await _rows_of(session_factory, c["id"], mfg) == []


async def test_legacy_backfill_replays_add_remove_readd(
        client, seed, ecr_template, departments, departments_member,
        session_factory, monkeypatch):
    """Old-format text: add approved, removal approved, re-add approved. The
    row of the re-add is backfilled; with the re-add rejected instead there
    is nothing to backfill."""
    import scripts.repair_routing_tasks as sweep_mod
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg = departments["Manufacturing Engineer"]
    await _add_remove_readd(client, auth, admin_auth, session_factory, c["id"], mfg)
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    await _strip_snapshot_entry(session_factory, c["id"], mfg)
    await _to_legacy_text(session_factory, c["id"])
    monkeypatch.setattr(sweep_mod, "AsyncSessionLocal", session_factory)
    assert await sweep_mod.backfill_snapshots(True, [c["id"]]) == 1
    assert await _snap_entries(session_factory, c["id"], mfg) == [
        (1, {"department_id": mfg, "rasic_letter": "R", "added_by_deviation": True})]


async def test_backfill_reads_only_the_current_routing(
        client, seed, ecr_template, departments, departments_member,
        session_factory, monkeypatch):
    """Entries written before the routing was (re)built belong to a routing
    torn down on a recall: the backfill ignores them."""
    import scripts.repair_routing_tasks as sweep_mod
    from datetime import datetime, timedelta
    from app.models.change import ChangeRouting
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    mfg = departments["Manufacturing Engineer"]
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": mfg, "rasic_letter": "R", "stage_order": 1,
        "reason": "x"}, headers=auth)).status_code == 200
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    await _strip_snapshot_entry(session_factory, c["id"], mfg)
    async with session_factory() as s:
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == c["id"]))).scalar_one()
        routing.created_at = datetime.utcnow() + timedelta(seconds=5)
        await s.commit()
    monkeypatch.setattr(sweep_mod, "AsyncSessionLocal", session_factory)
    assert await sweep_mod.backfill_snapshots(True, [c["id"]]) == 0


async def test_take_off_routing_waits_for_the_decision(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """The lead's "Take off routing" (a remove deviation) leaves the row owed
    until the decision: costing stays blocked on it, and only the approval
    deletes the row and its task."""
    from app.models.workflow import WfInstanceTask
    auth = await _login(client)          # the change lead
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    te = departments["Tool Engineer"]
    (row,) = await _rows_of(session_factory, c["id"], te)
    task_id = row.wf_instance_task_id
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "remove", "department_id": te, "stage_order": 1,
        "reason": "not involved after all"}, headers=auth)
    assert res.status_code == 200, res.text
    assert [r.id for r in await _rows_of(session_factory, c["id"], te)] == [row.id]
    async with session_factory() as s:
        assert (await s.get(WfInstanceTask, task_id)).status == "active"
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Quality"], "verdict": "feasible"},
                      headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition",
                            json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400, res.text
    assert (await client.post(f"/api/v1/changes/{c['id']}/routing/deviation/approve",
                              headers=admin_auth)).status_code == 200
    assert await _rows_of(session_factory, c["id"], te) == []
    async with session_factory() as s:
        assert await s.get(WfInstanceTask, task_id) is None
    assert await _snap_entries(session_factory, c["id"], te) == []


async def test_decisions_lock_a_completed_instance_before_the_routing(
        client, seed, ecr_template, departments, departments_member, session_factory,
        monkeypatch):
    """No active instance (every stage passed): approve, reject and the
    snapshot backfill lock the completed instance (lock_task_instance)
    BEFORE the routing, as apply_deviation does, so the repair that re-locks
    that instance afterwards never inverts the order."""
    from app.models.change import ChangeRequest
    from app.models.workflow import WfInstance
    from app.services.change_routing_service import ChangeRoutingService
    auth = await _login(client)
    c = await _in_costing_at_stage2(client, auth, seed, session_factory, departments)
    inst_id = await _complete_apqp(client, auth, session_factory, c["id"], departments["APQP"])
    calls: list[tuple[str, object]] = []
    orig_inst = ChangeRoutingService.lock_instance
    orig_task = ChangeRoutingService.lock_task_instance
    orig_routing = ChangeRoutingService._lock_routing

    async def rec_inst(session, change_id):
        r = await orig_inst(session, change_id)
        calls.append(("instance", r.id if r else None))
        return r

    async def rec_task(session, change_id):
        r = await orig_task(session, change_id)
        calls.append(("task_instance", r.id if r else None))
        return r

    async def rec_routing(session, change):
        calls.append(("routing", None))
        return await orig_routing(session, change)

    monkeypatch.setattr(ChangeRoutingService, "lock_instance", staticmethod(rec_inst))
    monkeypatch.setattr(ChangeRoutingService, "lock_task_instance", staticmethod(rec_task))
    monkeypatch.setattr(ChangeRoutingService, "_lock_routing", staticmethod(rec_routing))

    url = f"/api/v1/changes/{c['id']}/routing/deviation"
    for decide in ("approve", "reject"):
        dept = departments["Manufacturing Engineer" if decide == "approve" else "Sales"]
        assert (await client.post(url, json={
            "op": "add", "department_id": dept, "rasic_letter": "R", "stage_order": 2,
            "reason": "late find"}, headers=auth)).status_code == 200
        calls.clear()
        async with session_factory() as s:
            assert (await s.get(WfInstance, inst_id)).status == "completed"
            change = await s.get(ChangeRequest, c["id"])
            if decide == "approve":
                await ChangeRoutingService.approve_deviation(s, change, seed["admin_id"])
            else:
                await ChangeRoutingService.reject_deviation(s, change, seed["admin_id"], "no")
            await s.commit()
        first_routing = calls.index(("routing", None))
        assert calls[:first_routing] == [("instance", None), ("instance", None),
                                         ("task_instance", inst_id)], decide

    calls.clear()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, c["id"])
        await ChangeRoutingService.backfill_deviation_snapshot(s, change)
    assert calls[:3] == [("instance", None), ("instance", None),
                         ("task_instance", inst_id)]


async def test_legacy_relettered_text_keeps_the_approved_reletter_on_reject(
        client, seed, ecr_template, departments, departments_member, session_factory):
    """Prod text from before declines waited ("re-lettered dept N to X", no
    stage, the row re-lettered at request time, the snapshot untouched):
    the approved re-letter protects the row's letter in every stage of the
    department, so rejecting a later old-format deviation leaves it."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.change import ChangeChangelog, ChangeRouting
    from app.services.change_routing_service import _deviation_record
    auth = await _login(client)
    admin_auth = await _login_admin(client)
    c = await _api_change_in_assessment(client, auth, seed, session_factory)
    quality, sales = departments["Quality"], departments["Sales"]
    url = f"/api/v1/changes/{c['id']}/routing/deviation"
    assert (await client.post(url, json={"op": "reletter", "department_id": quality,
        "rasic_letter": "S", "reason": "support only"}, headers=auth)).status_code == 200
    assert (await client.post(url + "/approve", headers=admin_auth)).status_code == 200
    (row,) = await _rows_of(session_factory, c["id"], quality)
    assert row.rasic_letter == "S"
    async with session_factory() as s:
        # As written then: the snapshot kept the template's C, the entry
        # only the text.
        routing = (await s.execute(select(ChangeRouting).where(
            ChangeRouting.change_id == c["id"]))).scalar_one()
        snap = dict(routing.standard_snapshot)
        snap["stages"] = [{**st, "departments": [
            {**d, "rasic_letter": "C"} if d["department_id"] == quality else d
            for d in st["departments"]]} for st in snap["stages"]]
        routing.standard_snapshot = snap
        flag_modified(routing, "standard_snapshot")
        (entry,) = await _deviation_entries(session_factory, c["id"])
        e = await s.get(ChangeChangelog, entry.id)
        e.new_value = None
        e.action_description = f"Routing deviation: re-lettered dept {quality} to S"
        await s.commit()
        assert _deviation_record(e) == {
            "op": "reletter", "department_id": quality, "rasic_letter": "S",
            "stage_order": None, "legacy": True}
    assert (await client.post(url, json={"op": "add", "department_id": sales,
        "rasic_letter": "R", "stage_order": 1, "reason": "maybe"}, headers=auth)).status_code == 200
    async with session_factory() as s:
        entry = (await _deviation_entries(session_factory, c["id"]))[-1]
        e = await s.get(ChangeChangelog, entry.id)
        e.new_value = None
        e.action_description = f"Routing deviation: added dept {sales} as R in stage 1"
        await s.commit()
    res = await client.post(url + "/reject", json={"reason": "no"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    (row,) = await _rows_of(session_factory, c["id"], quality)
    assert row.rasic_letter == "S"
    assert await _rows_of(session_factory, c["id"], sales) == []
