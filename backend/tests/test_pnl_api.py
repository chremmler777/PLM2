"""Task 2: /api/v1/pnl/* endpoints — thin routes over PnlService, org-scoped
via viewer, mirrors reports.py router style."""
import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine
from app.models.entities import Plant
from app.models.workflow import Department
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pnl_api_data(session_factory, seed):
    async with session_factory() as s:
        dept = Department(name="R&D-PNL-API", flow_type="action")
        s.add(dept)
        await s.flush()
        plant_id = (await s.execute(select(Plant.id))).scalars().first()

        cust = ChangeRequest(
            change_number="CR-PNLAPI-001", title="Customer change", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="quoted",
            customer_relevant=True, quoted_price=5000.0,
        )
        s.add(cust)
        await s.flush()
        cust_assess = ChangeAssessment(change_id=cust.id, department_id=dept.id,
                                       verdict="feasible", effort_hours=1.0)
        s.add(cust_assess)
        await s.flush()
        s.add(AssessmentCostLine(
            assessment_id=cust_assess.id, plant_id=plant_id, cost_kind="one_time",
            demand_hours=10.0, rate_snapshot=100.0,
            internal_cost=1000.0, external_cost=0.0,
        ))

        internal = ChangeRequest(
            change_number="CR-PNLAPI-002", title="Internal change", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="costing",
            customer_relevant=False, internal_approved_amount=None,
        )
        s.add(internal)
        await s.flush()
        internal_assess = ChangeAssessment(change_id=internal.id, department_id=dept.id,
                                           verdict="feasible", effort_hours=1.0)
        s.add(internal_assess)
        await s.flush()
        s.add(AssessmentCostLine(
            assessment_id=internal_assess.id, plant_id=plant_id, cost_kind="one_time",
            demand_hours=5.0, rate_snapshot=100.0,
            internal_cost=500.0, external_cost=0.0,
        ))
        await s.commit()

        return {"cust_id": cust.id, "internal_id": internal.id}


async def test_changes_requires_auth(client):
    # HTTPBearer() with no Authorization header returns 403 (not 401 - that's
    # reserved for an invalid/expired token); consistent app-wide behavior.
    res = await client.get("/api/v1/pnl/changes")
    assert res.status_code == 403


async def test_summary_requires_auth(client):
    res = await client.get("/api/v1/pnl/summary")
    assert res.status_code == 403


async def test_changes_shape_for_admin(client, admin_auth, seed, pnl_api_data):
    res = await client.get("/api/v1/pnl/changes", headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {"rows"}
    ids = {r["change_id"] for r in body["rows"]}
    assert pnl_api_data["cust_id"] in ids
    assert pnl_api_data["internal_id"] in ids


async def test_summary_shape_for_admin(client, admin_auth, seed, pnl_api_data):
    res = await client.get("/api/v1/pnl/summary", headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {
        "totals", "pipeline", "realized", "by_project", "by_branch", "count"}
    assert body["count"] == 2


async def test_branch_filter_passthrough(client, admin_auth, seed, pnl_api_data):
    res = await client.get("/api/v1/pnl/changes?branch=internal", headers=admin_auth)
    assert res.status_code == 200, res.text
    rows = res.json()["rows"]
    assert rows
    assert all(r["branch"] == "internal" for r in rows)
    ids = {r["change_id"] for r in rows}
    assert pnl_api_data["internal_id"] in ids
    assert pnl_api_data["cust_id"] not in ids


async def test_invalid_branch_422(client, admin_auth):
    res = await client.get("/api/v1/pnl/changes?branch=bogus", headers=admin_auth)
    assert res.status_code == 422


async def test_invalid_status_group_422(client, admin_auth):
    res = await client.get("/api/v1/pnl/summary?status_group=bogus", headers=admin_auth)
    assert res.status_code == 422


async def test_date_range_passthrough(client, admin_auth, seed, pnl_api_data):
    res = await client.get(
        "/api/v1/pnl/changes?date_from=2020-01-01&date_to=2020-12-31",
        headers=admin_auth)
    assert res.status_code == 200, res.text
    ids = {r["change_id"] for r in res.json()["rows"]}
    assert pnl_api_data["cust_id"] not in ids
    assert pnl_api_data["internal_id"] not in ids


async def test_invalid_date_from_422(client, admin_auth):
    res = await client.get("/api/v1/pnl/changes?date_from=not-a-date", headers=admin_auth)
    assert res.status_code == 422


async def test_invalid_date_to_422(client, admin_auth):
    res = await client.get("/api/v1/pnl/summary?date_to=not-a-date", headers=admin_auth)
    assert res.status_code == 422
