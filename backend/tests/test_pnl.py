"""Task 1: PnlService — per-change P&L rows and summary aggregation.

P&L is computed live from existing change-management data (no new tables):
revenue is `quoted_price` (customer changes) or `internal_approved_amount`
(internal changes); cost is the sum of AssessmentCostLine actuals joined via
ChangeAssessment. Only changes in status 'costing' or beyond are in scope.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine
from app.models.entities import Organization, Plant, Project, User
from app.models.workflow import Department
from app.services.change_service import ChangeService
from app.auth.security import get_password_hash

pytestmark = pytest.mark.asyncio


async def _dept(s, name="R&D-PNL"):
    d = Department(name=name, flow_type="action")
    s.add(d)
    await s.flush()
    return d


@pytest.fixture
async def pnl_data(session_factory, seed):
    async with session_factory() as s:
        dept = await _dept(s)
        plant_id = (await s.execute(select(Plant.id))).scalars().first()

        # Customer-relevant change in 'quoted': revenue = quoted_price.
        cust = ChangeRequest(
            change_number="CR-PNL-001", title="Customer change", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="quoted",
            customer_relevant=True, quoted_price=10000.0,
            raised_at=datetime(2026, 1, 15),
        )
        s.add(cust)
        await s.flush()
        cust_assess = ChangeAssessment(change_id=cust.id, department_id=dept.id,
                                       verdict="feasible", effort_hours=2.5)
        s.add(cust_assess)
        await s.flush()
        s.add(AssessmentCostLine(
            assessment_id=cust_assess.id, plant_id=plant_id, cost_kind="one_time",
            demand_hours=40.0, rate_snapshot=100.0,
            internal_cost=4000.0, external_cost=2000.0,
        ))

        # Internal change in 'costing': revenue = internal_approved_amount,
        # not yet approved.
        internal = ChangeRequest(
            change_number="CR-PNL-002", title="Internal change", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="costing",
            customer_relevant=False, internal_approved_amount=None,
            raised_at=datetime(2026, 3, 10),
        )
        s.add(internal)
        await s.flush()
        internal_assess = ChangeAssessment(change_id=internal.id, department_id=dept.id,
                                          verdict="feasible", effort_hours=1.0)
        s.add(internal_assess)
        await s.flush()
        s.add(AssessmentCostLine(
            assessment_id=internal_assess.id, plant_id=plant_id, cost_kind="one_time",
            demand_hours=30.0, rate_snapshot=100.0,
            internal_cost=3000.0, external_cost=0.0,
        ))

        # Pre-costing change: never appears in P&L.
        pre_costing = ChangeRequest(
            change_number="CR-PNL-003", title="Pre-costing change", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment",
            customer_relevant=False,
        )
        s.add(pre_costing)
        await s.flush()

        # Internal change already 'approved': excluded from status_group=pipeline.
        approved = ChangeRequest(
            change_number="CR-PNL-004", title="Approved change", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="approved",
            customer_relevant=False, internal_approved_amount=1000.0,
        )
        s.add(approved)
        await s.flush()

        # Org B: a second org, invisible to org A's non-admin viewer.
        org_b = Organization(name="PNL Org B", code="pnl-org-b", is_active=True)
        s.add(org_b)
        await s.flush()
        plant_b = Plant(organization_id=org_b.id, name="Plant PB", code="plant-pb",
                        location="US", is_active=True)
        s.add(plant_b)
        await s.flush()
        project_b = Project(plant_id=plant_b.id, name="Project PB", code="proj-pb", status="active")
        s.add(project_b)
        await s.flush()
        user_b = User(
            organization_id=org_b.id, username="pnlorgb", email="pnlorgb@test.io",
            full_name="PNL Org B User", hashed_password=get_password_hash("pnl-org-b-1"),
            role="engineer", is_active=True, mfa_enabled=False,
        )
        s.add(user_b)
        await s.flush()
        change_b = ChangeRequest(
            change_number="CR-PNL-B01", title="Org B change", reason="r",
            change_type="physical_part", project_id=project_b.id,
            raised_by=user_b.id, status="costing", customer_relevant=False,
            internal_approved_amount=None,
        )
        s.add(change_b)
        await s.commit()

        return {
            "dept_id": dept.id,
            "cust_id": cust.id, "internal_id": internal.id,
            "pre_costing_id": pre_costing.id, "approved_id": approved.id,
            "change_b_id": change_b.id, "user_b_id": user_b.id,
        }


async def _admin(session_factory, seed) -> User:
    async with session_factory() as s:
        return await s.get(User, seed["admin_id"])


async def test_changes_pnl_rows(session_factory, seed, pnl_data):
    from app.services.pnl_service import PnlService
    async with session_factory() as session:
        admin = await session.get(User, seed["admin_id"])
        rows = await PnlService.changes_pnl(session, admin)
        cust = next(r for r in rows if r["branch"] == "customer")
        assert cust["revenue"] == 10000.0
        assert cust["total_cost"] == 6000.0
        assert cust["margin"] == 4000.0
        assert cust["margin_pct"] == 40.0
        assert cust["internal_cost"] == 4000.0
        assert cust["external_cost"] == 2000.0
        assert cust["effort_hours"] == 2.5
        assert cust["pending_price"] is False
        assert cust["realized"] is False  # 'quoted' is pre-realized


async def test_internal_branch_uses_approved_amount(session_factory, seed, pnl_data):
    from app.services.pnl_service import PnlService
    async with session_factory() as session:
        admin = await session.get(User, seed["admin_id"])

        rows = await PnlService.changes_pnl(session, admin)
        internal_row = next(r for r in rows if r["change_id"] == pnl_data["internal_id"])
        assert internal_row["pending_price"] is True
        assert internal_row["revenue"] is None
        assert internal_row["margin"] is None
        assert internal_row["margin_pct"] is None
        assert internal_row["total_cost"] == 3000.0

        change = await session.get(ChangeRequest, pnl_data["internal_id"])
        await ChangeService.approve_internal_costs(session, change, admin)
        await session.commit()

        rows = await PnlService.changes_pnl(session, admin)
        internal_row = next(r for r in rows if r["change_id"] == pnl_data["internal_id"])
        snapshot = internal_row["revenue"]
        assert snapshot is not None
        assert internal_row["pending_price"] is False
        assert internal_row["margin"] == snapshot - internal_row["total_cost"]


async def test_excludes_pre_costing_statuses(session_factory, seed, pnl_data):
    from app.services.pnl_service import PnlService
    async with session_factory() as session:
        admin = await session.get(User, seed["admin_id"])
        rows = await PnlService.changes_pnl(session, admin)
        ids = {r["change_id"] for r in rows}
        assert pnl_data["pre_costing_id"] not in ids


async def test_filters(session_factory, seed, pnl_data):
    from app.services.pnl_service import PnlService
    async with session_factory() as session:
        admin = await session.get(User, seed["admin_id"])

        internal_rows = await PnlService.changes_pnl(session, admin, branch="internal")
        assert all(r["branch"] == "internal" for r in internal_rows)
        assert any(r["change_id"] == pnl_data["internal_id"] for r in internal_rows)
        assert not any(r["change_id"] == pnl_data["cust_id"] for r in internal_rows)

        pipeline_rows = await PnlService.changes_pnl(session, admin, status_group="pipeline")
        pipeline_ids = {r["change_id"] for r in pipeline_rows}
        assert pnl_data["approved_id"] not in pipeline_ids
        assert pnl_data["cust_id"] in pipeline_ids
        assert pnl_data["internal_id"] in pipeline_ids


async def test_date_range_filter(session_factory, seed, pnl_data):
    from app.services.pnl_service import PnlService
    async with session_factory() as session:
        admin = await session.get(User, seed["admin_id"])

        # In range: only cust (raised 2026-01-15).
        rows = await PnlService.changes_pnl(
            session, admin, date_from="2026-01-01", date_to="2026-01-31")
        ids = {r["change_id"] for r in rows}
        assert ids == {pnl_data["cust_id"]}

        # date_from only: excludes cust, includes internal (2026-03-10).
        rows = await PnlService.changes_pnl(session, admin, date_from="2026-02-01")
        ids = {r["change_id"] for r in rows}
        assert pnl_data["cust_id"] not in ids
        assert pnl_data["internal_id"] in ids

        # date_to only: includes cust, excludes internal.
        rows = await PnlService.changes_pnl(session, admin, date_to="2026-01-31")
        ids = {r["change_id"] for r in rows}
        assert ids == {pnl_data["cust_id"]}

        # date_to is inclusive of the whole day.
        rows = await PnlService.changes_pnl(session, admin, date_to="2026-01-15")
        ids = {r["change_id"] for r in rows}
        assert pnl_data["cust_id"] in ids

        s = await PnlService.summary(
            session, admin, date_from="2026-01-01", date_to="2026-01-31")
        assert s["count"] == 1


async def test_summary_shape_and_totals(session_factory, seed, pnl_data):
    from app.services.pnl_service import PnlService
    async with session_factory() as session:
        admin = await session.get(User, seed["admin_id"])
        s = await PnlService.summary(session, admin)

        assert s["totals"]["margin"] == pytest.approx(
            s["totals"]["revenue"] - s["totals"]["total_cost"])
        assert set(s["by_branch"]) == {"customer", "internal"}
        assert set(s.keys()) == {
            "totals", "pipeline", "realized", "by_project", "by_branch", "count"}
        # cust(quoted) + internal(costing) + approved(approved) + org B's
        # change (admin bypasses org scoping) all in scope.
        assert s["count"] == 4
        assert s["by_branch"]["customer"]["revenue"] == 10000.0
        # None revenue (internal, not yet approved) counted as 0 in sums.
        assert s["totals"]["revenue"] == 10000.0 + 0.0 + 1000.0
        proj_row = next(p for p in s["by_project"] if p["project_id"] == seed["project_id"])
        assert proj_row["revenue"] == s["totals"]["revenue"]


async def test_org_scoping(session_factory, seed, pnl_data):
    from app.services.pnl_service import PnlService
    async with session_factory() as session:
        # A non-admin viewer in org A must never see org B's change.
        engineer = await session.get(User, seed["engineer_id"])
        rows = await PnlService.changes_pnl(session, engineer)
        ids = {r["change_id"] for r in rows}
        assert pnl_data["change_b_id"] not in ids
        assert pnl_data["cust_id"] in ids

        s = await PnlService.summary(session, engineer)
        assert s["count"] == 3
