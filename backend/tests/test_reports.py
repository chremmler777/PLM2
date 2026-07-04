"""Task 14: ReportService + /v1/reports/* live SQL aggregates.

Fixture: 2 changes in org A (one released on time vs required_by_date, one
in_assessment with an overdue owned task), 1 change in org B (must stay
invisible to org A's viewer).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine
from app.models.entities import AuditLog, Organization, Plant, Project, User
from app.models.workflow import Department, WfInstance, WfInstanceTask, WfTemplate

from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def report_data(session_factory, seed):
    now = datetime.utcnow()
    async with session_factory() as s:
        dept = Department(name="R&D-Reports", flow_type="action")
        s.add(dept)
        await s.flush()

        # change1: released on time (required_by_date in the future, released
        # 1 day ago) - eligible for on_time_rate.
        change1 = ChangeRequest(
            change_number="CR-RPT-001", title="On-time change",
            reason="r", change_type="physical_part",
            project_id=seed["project_id"], raised_by=seed["engineer_id"],
            lead_id=seed["engineer_id"], status="released",
            released_at=now - timedelta(days=1),
            required_by_date=now + timedelta(days=5),
            estimated_cost=500.0,
        )
        s.add(change1)
        await s.flush()

        # change2: in_assessment, with an overdue owned workflow task.
        change2 = ChangeRequest(
            change_number="CR-RPT-002", title="At-risk change",
            reason="r", change_type="physical_part",
            project_id=seed["project_id"], raised_by=seed["engineer_id"],
            lead_id=seed["engineer_id"], status="in_assessment",
        )
        s.add(change2)
        await s.flush()

        template = WfTemplate(name="Reports Test Template", created_by=seed["engineer_id"])
        s.add(template)
        await s.flush()
        inst = WfInstance(template_id=template.id, change_id=change2.id, status="active",
                          current_stage_order=1, started_by=seed["engineer_id"])
        s.add(inst)
        await s.flush()
        task = WfInstanceTask(
            instance_id=inst.id, stage_order=1, step_id=None, department_id=dept.id,
            rasic_letter="R", status="active", is_actionable=True,
            owner_id=seed["engineer_id"], due_date=now - timedelta(days=1),
        )
        s.add(task)
        await s.flush()

        # AuditLog transitions on change2: two entries 3 days apart ->
        # pair (captured, in_assessment) avg_days ~= 3.0.
        t0 = now - timedelta(days=10)
        s.add(AuditLog(
            entity_type="change", entity_id=change2.id, action="status_changed",
            user_id=seed["engineer_id"], timestamp=t0,
            old_values='"captured"', new_values='"in_assessment"',
            correlation_id=change2.change_number,
        ))
        s.add(AuditLog(
            entity_type="change", entity_id=change2.id, action="status_changed",
            user_id=seed["engineer_id"], timestamp=t0 + timedelta(days=3),
            old_values='"in_assessment"', new_values='"costing"',
            correlation_id=change2.change_number,
        ))

        # Cost lines on change1's assessment.
        plant_id = (await s.execute(select(Plant.id))).scalars().first()
        assessment = ChangeAssessment(change_id=change1.id, department_id=dept.id,
                                      verdict="pending")
        s.add(assessment)
        await s.flush()
        s.add(AssessmentCostLine(
            assessment_id=assessment.id, plant_id=plant_id, cost_kind="one_time",
            demand_hours=1.0, rate_snapshot=100.0, internal_cost=100.0, external_cost=50.0,
        ))

        # Org B: a second org/plant/project/user/change, invisible to org A.
        org_b = Organization(name="Report Org B", code="report-org-b", is_active=True)
        s.add(org_b)
        await s.flush()
        plant_b = Plant(organization_id=org_b.id, name="Plant RB", code="plant-rb",
                        location="US", is_active=True)
        s.add(plant_b)
        await s.flush()
        project_b = Project(plant_id=plant_b.id, name="Project RB", code="proj-rb", status="active")
        s.add(project_b)
        await s.flush()
        user_b = User(
            organization_id=org_b.id, username="reportorgb", email="reportorgb@test.io",
            full_name="Report Org B User", hashed_password=get_password_hash("report-org-b-1"),
            role="engineer", is_active=True, mfa_enabled=False,
        )
        s.add(user_b)
        await s.flush()
        change_b = ChangeRequest(
            change_number="CR-RPT-B01", title="Org B change",
            reason="r", change_type="physical_part",
            project_id=project_b.id, raised_by=user_b.id, status="in_assessment",
        )
        s.add(change_b)
        await s.commit()

        return {
            "dept_id": dept.id, "change1_id": change1.id, "change2_id": change2.id,
            "task_id": task.id, "change_b_id": change_b.id,
            "project_id": seed["project_id"],
        }


async def test_pipeline_report(client, eng_auth, seed, report_data):
    res = await client.get("/api/v1/reports/pipeline", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()

    funnel = {row["status"]: row["count"] for row in body["funnel"]}
    assert len(body["funnel"]) == 12
    assert funnel["in_assessment"] == 1
    assert funnel["released"] == 1
    assert funnel["captured"] == 0

    assert body["on_time_rate"] == 1.0

    assert len(body["throughput"]) == 12
    assert sum(m["released"] for m in body["throughput"]) == 1

    pairs = {(a["from_status"], a["to_status"]): a["avg_days"] for a in body["avg_stage_days"]}
    assert ("captured", "in_assessment") in pairs
    assert pairs[("captured", "in_assessment")] == pytest.approx(3.0, abs=0.05)


async def test_workload_report(client, eng_auth, seed, report_data):
    res = await client.get("/api/v1/reports/workload", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()

    assert len(body["departments"]) == 1
    dept_row = body["departments"][0]
    assert dept_row["department_id"] == report_data["dept_id"]
    assert dept_row["open"] == 1
    assert dept_row["overdue"] == 1

    assert len(body["owners"]) == 1
    owner_row = body["owners"][0]
    assert owner_row["owner_id"] == seed["engineer_id"]
    assert owner_row["open"] == 1
    assert owner_row["overdue"] == 1

    assert body["at_risk_changes"] == []
    assert body["escalation_count"] == 1


async def test_cost_report(client, eng_auth, seed, report_data):
    res = await client.get("/api/v1/reports/cost", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()

    assert len(body["projects"]) == 1
    proj = body["projects"][0]
    assert proj["project_id"] == seed["project_id"]
    assert proj["actual"] == pytest.approx(150.0)
    assert proj["budget"] == pytest.approx(500.0)

    assert len(body["plants"]) == 1
    assert body["plants"][0]["actual"] == pytest.approx(150.0)


async def test_org_scoping_hides_org_b(client, eng_auth, seed, report_data):
    res = await client.get("/api/v1/reports/pipeline", headers=eng_auth)
    assert res.status_code == 200, res.text
    funnel = {row["status"]: row["count"] for row in res.json()["funnel"]}
    # 2 org-A changes total (released + in_assessment); org B's change must
    # not bump any bucket beyond that.
    assert sum(funnel.values()) == 2


async def test_empty_db_zero_filled_shapes(client, eng_auth, seed):
    """A fresh org with no changes at all - every endpoint stays 200 with
    zero-filled shapes, no division-by-zero."""
    res = await client.get("/api/v1/reports/pipeline", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["funnel"]) == 12
    assert all(row["count"] == 0 for row in body["funnel"])
    assert len(body["throughput"]) == 12
    assert all(m["released"] == 0 for m in body["throughput"])
    assert body["avg_stage_days"] == []
    assert body["on_time_rate"] is None

    res = await client.get("/api/v1/reports/workload", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {"departments": [], "owners": [], "at_risk_changes": [], "escalation_count": 0}

    res = await client.get("/api/v1/reports/cost", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json() == {"projects": [], "plants": []}
