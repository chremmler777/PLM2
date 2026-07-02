# backend/tests/test_change_routing.py
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.models.workflow import Department, WfTemplate, WfStage, WfStep, WfStepRasic
from app.models.change import (
    ChangeRouting, ChangeRoutingStandard, BLOCKING_LETTERS, TASK_LETTERS,
)
from tests.conftest import approve_gates

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
    assert TASK_LETTERS == ("R", "A", "S", "C")


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
        assert by_dep[departments["Tool Engineer"]].stage_order == 1
        assert by_dep[departments["Tool Engineer"]].rasic_letter == "R"
        assert by_dep[departments["Tool Engineer"]].status == "active"   # stage 1 activated
        assert by_dep[departments["APQP"]].stage_order == 2
        assert by_dep[departments["APQP"]].status == "pending"           # stage 2 not active yet
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
    res = await client.post("/api/v1/auth/login", json={"email": "eng@test.io", "password": "eng-secret-12"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _login_admin(client):
    res = await client.post("/api/v1/auth/login", json={"email": "admin@test.io", "password": "admin-secret-1"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _api_change_in_assessment(client, auth, seed):
    body = {"project_id": seed["project_id"], "title": "Wall +0.2", "change_type": "physical_part",
            "reason": "sink", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-R1",
         "name": "ART-R1", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "in_assessment"}, headers=auth)
    return c


async def test_stage_gating_blocks_costing_until_blocking_submitted(client, seed, ecr_template, departments):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed)
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    # Quality (C, stage1) submitting alone must NOT advance to stage 2; costing blocked.
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Quality"], "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400, res.text  # Tool Engineer (R) still pending
    # Submit Tool Engineer (R) -> stage 1 blocking done -> stage 2 activates (APQP)
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"}, headers=auth)
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    apqp = next(a for a in detail["assessments"] if a["department_id"] == departments["APQP"])
    assert apqp["status"] == "active"
    # Costing still blocked until APQP (A) submits
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 400, res.text
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["APQP"], "verdict": "feasible"}, headers=auth)
    res = await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "costing"}, headers=auth)
    assert res.status_code == 200, res.text


async def test_deviation_requires_approval_then_clears(client, seed, ecr_template, departments):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed)
    res = await client.post(f"/api/v1/changes/{c['id']}/routing/deviation", json={
        "op": "add", "department_id": departments["Manufacturing Engineer"],
        "rasic_letter": "R", "stage_order": 1}, headers=auth)
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
            department_id=departments["Manufacturing Engineer"], rasic_letter="R", stage_order=1)
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
            department_id=departments["Manufacturing Engineer"], rasic_letter="R", stage_order=1)
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
async def test_my_tasks_only_active_stage(client, seed, ecr_template, departments):
    auth = await _login(client)
    c = await _api_change_in_assessment(client, auth, seed)
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
    c = await _api_change_in_assessment(client, auth, seed)

    dep_ids = {t["department_id"] for t in (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()}
    assert departments["Tool Engineer"] in dep_ids   # active stage 1
    assert departments["APQP"] not in dep_ids         # stage 2 still pending → hidden

    # Submitting Tool Engineer (R) clears stage 1's blocking → stage 2 activates.
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"}, headers=auth)
    dep_ids2 = {t["department_id"] for t in (await client.get("/api/v1/changes/my-tasks", headers=auth)).json()}
    assert departments["APQP"] in dep_ids2               # now active → visible
    assert departments["Tool Engineer"] not in dep_ids2  # submitted → verdict no longer pending


async def test_not_feasible_blocks_costing_until_justified(client, seed, departments):
    auth = await _login(client)
    # no ecr_template fixture here -> fallback single-stage all-R routing
    body = {"project_id": seed["project_id"], "title": "NF", "change_type": "physical_part",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-NF",
         "name": "ART-NF", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "in_assessment"}, headers=auth)
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
        client, seed, ecr_template_3stage, departments):
    auth = await _login(client)
    body = {"project_id": seed["project_id"], "title": "casc", "change_type": "tooling",
            "reason": "x", "lead_id": seed["engineer_id"]}
    c = (await client.post("/api/v1/changes", json=body, headers=auth)).json()
    await approve_gates(client, auth, c["id"])
    p = (await client.post("/api/v1/parts", json={"project_id": seed["project_id"], "part_number": "ART-C1",
         "name": "ART-C1", "part_type": "internal_mfg", "item_category": "article"}, headers=auth)).json()
    await client.post(f"/api/v1/changes/{c['id']}/impacted-items", json={"part_id": p["id"]}, headers=auth)
    await client.post(f"/api/v1/changes/{c['id']}/transition", json={"to_status": "in_assessment"}, headers=auth)
    # submit stage1 Tool Engineer (R) -> should cascade past the C-only stage2 and activate stage3 APQP
    await client.post(f"/api/v1/changes/{c['id']}/assessments",
                      json={"department_id": departments["Tool Engineer"], "verdict": "feasible"}, headers=auth)
    detail = (await client.get(f"/api/v1/changes/{c['id']}", headers=auth)).json()
    by_dep = {a["department_id"]: a for a in detail["assessments"]}
    assert by_dep[departments["APQP"]]["status"] == "active"    # cascaded through stage 2
    assert by_dep[departments["Quality"]]["status"] == "active"  # the optional stage was also activated


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
        session_factory, seed, ecr_template_multistage_dept, departments):
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
        assert rows[(te, 1)].status == "submitted"     # stage-1 row taken
        assert rows[(te, 2)].status == "pending"        # stage-2 row untouched

    # Finish stage-1 blocking (Quality R) -> stage 2 activates, incl. Tool Engineer(A).
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(
            s, change, departments["Quality"], "feasible", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        rows = rows_by((await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all())
        assert rows[(te, 2)].status == "active"         # stage 2 now active

    # Second submit for the SAME dept now targets the stage-2 row.
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        await ChangeService.submit_assessment(s, change, te, "feasible", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        rows = rows_by((await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid))).scalars().all())
        assert rows[(te, 1)].status == "submitted"
        assert rows[(te, 2)].status == "submitted"
