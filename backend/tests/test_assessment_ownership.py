# backend/tests/test_assessment_ownership.py
from datetime import datetime

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _routed_change(client, eng_auth, seed, session_factory, part_id):
    """Change routed into in_assessment via the standard flow."""
    from tests.conftest import approve_gates
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "own", "change_type": "tooling",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    change = res.json()
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": part_id, "is_lead": True},
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    await approve_gates(client, eng_auth, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    return change


async def test_assessments_get_due_date_on_activation(
        client, eng_auth, seed, session_factory, part):
    """Engine activation stamps due dates: the started stage's actionable (R/A)
    tasks carry a due date (read through by effective_due_date on their linked
    rows); a not-yet-started stage's rows are effectively pending with no due."""
    from app.models.change import ChangeAssessment, ChangeRoutingStandard
    from app.models.workflow import (
        Department, WfTemplate, WfStage, WfStep, WfStepRasic,
    )
    async with session_factory() as s:
        dep = {}
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            d = Department(name=n, flow_type="change", is_active=True)
            s.add(d); await s.flush(); dep[n] = d.id
        # Two-stage standard for "tooling": stage1 R+R (actionable), stage2 A.
        t = WfTemplate(name="ECR-tooling", description="x", version=1,
                       is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [(1, [("Tool Engineer", "R"), ("Process Engineer", "R")]),
                  (2, [("Manufacturing Engineer", "A")])]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"S{order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=dep[name], rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="tooling", template_id=t.id,
                                    template_version=1, updated_by=1))
        await s.commit()
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"]))).scalars().all()
        assert rows
        active = [a for a in rows if a.effective_status == "active"]
        assert active
        assert all(a.effective_due_date is not None for a in active)
        pending = [a for a in rows if a.effective_status == "pending"]
        assert all(a.effective_due_date is None for a in pending)


async def test_accept_assessment_delegates_to_linked_task(
        client, eng_auth, seed, session_factory, part):
    """Phase E: for an R/A row linked to an engine task, POST .../accept must
    write ownership onto the WfInstanceTask (the source of truth) rather than
    the assessment row, and the response must read it back through
    effective_owner_id/effective_accepted_at/effective_status."""
    from app.models.change import ChangeAssessment, ChangeRoutingStandard
    from app.models.workflow import (
        Department, WfTemplate, WfStage, WfStep, WfStepRasic, UserDepartment,
        WfInstanceTask,
    )
    async with session_factory() as s:
        dep = {}
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            d = Department(name=n, flow_type="change", is_active=True)
            s.add(d); await s.flush(); dep[n] = d.id
        t = WfTemplate(name="ECR-tooling-accept", description="x", version=1,
                       is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [(1, [("Tool Engineer", "R"), ("Process Engineer", "R")]),
                  (2, [("Manufacturing Engineer", "A")])]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"S{order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=dep[name], rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="tooling", template_id=t.id,
                                    template_version=1, updated_by=1))
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dep["Tool Engineer"]))
        await s.commit()

    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])

    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.department_id == dep["Tool Engineer"]))).scalar_one()
        assert a.wf_instance_task_id is not None, "stage-1 R row must link to a task"
        assessment_id, task_id = a.id, a.wf_instance_task_id

    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{assessment_id}/accept",
        headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["owner_id"] == seed["engineer_id"]
    assert body["accepted_at"] is not None
    assert body["status"] == "active"   # effective_status, read through the task

    async with session_factory() as s:
        a2 = await s.get(ChangeAssessment, assessment_id)
        assert a2.status == "pending"   # row itself untouched
        assert a2.owner_id is None
        assert a2.accepted_at is None
        task = await s.get(WfInstanceTask, task_id)
        assert task.owner_id == seed["engineer_id"]   # task is the source of truth
        assert task.accepted_at is not None


async def _activate_first_assessment(session_factory, change_id):
    """Directly mark the change's first assessment row raw-'active' with a due date.

    Post-Phase-E the normal flow keeps R/A execution state on engine tasks and
    leaves assessment rows 'pending'; unlinked raw-'active' rows are what routing
    deviations produce. The assessment-ownership endpoints (accept/assign/
    due-date) operate on such rows, so we set one up directly here (no engine
    instance in this fallback change, so the row stays unlinked)."""
    from datetime import datetime, timedelta
    from app.models.change import ChangeAssessment
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment)
             .where(ChangeAssessment.change_id == change_id)
             .order_by(ChangeAssessment.id))).scalars().first()
        a.status = "active"
        a.due_date = datetime.utcnow() + timedelta(days=7)
        await s.commit()
        return a


async def test_accept_and_assign_assessment(client, eng_auth, admin_auth, seed,
                                            session_factory, part):
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            s.add(Department(name=n, flow_type="action", is_active=True))
        await s.commit()
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    a = await _activate_first_assessment(session_factory, change["id"])
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=a.department_id))
        await s.commit()

    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/accept",
        headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["owner_id"] == seed["engineer_id"]
    assert body["accepted_at"] is not None

    # admin assigns back to engineer -> accepted_at cleared
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/assign",
        json={"user_id": seed["engineer_id"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["accepted_at"] is None

    # non-member assignee refused
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/assign",
        json={"user_id": seed["admin_id"]}, headers=admin_auth)
    assert res.status_code == 400


async def test_assign_linked_assessment_lead_carveout(
        client, eng_auth, seed, session_factory, part):
    """Important-severity regression: assign_assessment now delegates linked
    R/A rows to WorkflowService.assign_task (Task 7). set_task_due_date has
    a change-lead carve-out (admin OR workflow-starter OR change lead); the
    legacy assign_assessment authz allowed admin OR lead OR department member.
    assign_task must gain the identical lead carve-out so a change lead who
    is NOT a department member can still assign a linked, blocking (R/A)
    assessment task."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.change import ChangeAssessment, ChangeRoutingStandard
    from app.models.workflow import (
        Department, WfTemplate, WfStage, WfStep, WfStepRasic, UserDepartment,
        WfInstanceTask,
    )
    from tests.conftest import login, approve_gates

    async with session_factory() as s:
        dep = {}
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            d = Department(name=n, flow_type="change", is_active=True)
            s.add(d); await s.flush(); dep[n] = d.id
        t = WfTemplate(name="ECR-tooling-leadassign", description="x", version=1,
                       is_active=True, created_by=1)
        s.add(t); await s.flush()
        layout = [(1, [("Tool Engineer", "R"), ("Process Engineer", "R")]),
                  (2, [("Manufacturing Engineer", "A")])]
        for order, deps in layout:
            stage = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
            s.add(stage); await s.flush()
            step = WfStep(stage_id=stage.id, step_name=f"S{order}", position_in_stage=1)
            s.add(step); await s.flush()
            for name, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=dep[name], rasic_letter=letter))
        s.add(ChangeRoutingStandard(change_type="tooling", template_id=t.id,
                                    template_version=1, updated_by=1))
        # Engineer is a member of Tool Engineer (the assignee's department).
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dep["Tool Engineer"]))
        # A separate, non-admin, non-member user who will be the change lead.
        lead = User(
            organization_id=seed["org_id"], username="lead2", email="lead2@test.io",
            full_name="Lead Two", hashed_password=get_password_hash("lead2-secret-1"),
            role="engineer", is_active=True, mfa_enabled=False,
        )
        s.add(lead)
        await s.commit()
        await s.refresh(lead)
        lead_id = lead.id

    lead_auth = await login(client, "lead2@test.io", "lead2-secret-1")

    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "lead-assign", "change_type": "tooling",
        "lead_id": lead_id}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    change = res.json()
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": part["part_id"], "is_lead": True},
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    await approve_gates(client, lead_auth, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=lead_auth)
    assert res.status_code == 200, res.text

    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"],
            ChangeAssessment.department_id == dep["Tool Engineer"]))).scalar_one()
        assert a.wf_instance_task_id is not None, "stage-1 R row must link to a task"
        assessment_id, task_id = a.id, a.wf_instance_task_id

    # lead2 is neither admin nor a member of Tool Engineer, but is the change
    # lead: must be allowed to assign the linked, blocking task.
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{assessment_id}/assign",
        json={"user_id": seed["engineer_id"]}, headers=lead_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["owner_id"] == seed["engineer_id"]

    async with session_factory() as s:
        task = await s.get(WfInstanceTask, task_id)
        assert task.owner_id == seed["engineer_id"]


async def test_assessment_due_date_lead_only(client, eng_auth, admin_auth, seed,
                                             session_factory, part):
    from datetime import datetime, timedelta
    from app.models.workflow import Department
    async with session_factory() as s:
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            s.add(Department(name=n, flow_type="action", is_active=True))
        await s.commit()
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    a = await _activate_first_assessment(session_factory, change["id"])
    new_due = (datetime.utcnow() + timedelta(days=3)).isoformat()

    # engineer IS the lead (fixture sets lead_id) -> allowed
    res = await client.put(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/due-date",
        json={"due_date": new_due}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["due_date"] is not None

    # ownership events are in the changelog/audit
    from app.models.entities import AuditLog
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.correlation_id == change["change_number"],
            AuditLog.action == "assessment_due_date_set"))).scalars().all()
    assert len(rows) == 1
