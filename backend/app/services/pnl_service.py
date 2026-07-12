"""P&L (Profit & Loss) read model: per-change and portfolio-level margin views.

Computed live from existing change-management data (no new tables, no
migration). Revenue is `quoted_price` for customer-relevant changes or
`internal_approved_amount` (the PM-approved summation snapshot) for internal
changes. Cost is the sum of AssessmentCostLine actuals joined through
ChangeAssessment. Only changes in status 'costing' or beyond are in scope -
mirrors ReportService's org-scoping via `_org_scope`.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine
from app.models.entities import Project, User
from app.services.report_service import _org_scope

PNL_STATUSES = ("costing", "quoted", "approved", "in_implementation",
                "in_validation", "released", "closed")
REALIZED_STATUSES = PNL_STATUSES[2:]
PIPELINE_STATUSES = ("costing", "quoted")


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    return date.fromisoformat(value)


class PnlService:

    @staticmethod
    async def changes_pnl(
        session: AsyncSession, viewer: Optional[User], *,
        project_id: Optional[int] = None, plant_id: Optional[int] = None,
        branch: Optional[str] = None, status_group: Optional[str] = None,
        date_from: Optional[str] = None, date_to: Optional[str] = None,
    ) -> list[dict]:
        if status_group == "pipeline":
            statuses = PIPELINE_STATUSES
        elif status_group == "realized":
            statuses = REALIZED_STATUSES
        else:
            statuses = PNL_STATUSES

        stmt = select(ChangeRequest).where(ChangeRequest.status.in_(statuses))
        if project_id is not None:
            stmt = stmt.where(ChangeRequest.project_id == project_id)
        if branch == "customer":
            stmt = stmt.where(ChangeRequest.customer_relevant.is_(True))
        elif branch == "internal":
            stmt = stmt.where(ChangeRequest.customer_relevant.is_(False))
        parsed_from = _parse_date(date_from)
        if parsed_from is not None:
            stmt = stmt.where(ChangeRequest.raised_at >= datetime.combine(
                parsed_from, datetime.min.time()))
        parsed_to = _parse_date(date_to)
        if parsed_to is not None:
            stmt = stmt.where(ChangeRequest.raised_at < datetime.combine(
                parsed_to, datetime.min.time()) + timedelta(days=1))
        stmt = _org_scope(stmt, viewer)
        changes = (await session.execute(stmt)).scalars().all()
        if not changes:
            return []
        change_ids = [c.id for c in changes]

        # Single grouped cost query across every change in scope - never call
        # CostService.summation per change (N+1 query trap).
        cost_rows = (await session.execute(
            select(ChangeAssessment.change_id,
                   func.coalesce(func.sum(AssessmentCostLine.internal_cost), 0.0),
                   func.coalesce(func.sum(AssessmentCostLine.external_cost), 0.0))
            .select_from(AssessmentCostLine)
            .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
            .where(ChangeAssessment.change_id.in_(change_ids))
            .group_by(ChangeAssessment.change_id)
        )).all()
        costs = {cid: (internal or 0.0, external or 0.0)
                 for cid, internal, external in cost_rows}

        if plant_id is not None:
            plant_change_ids = set((await session.execute(
                select(ChangeAssessment.change_id)
                .select_from(AssessmentCostLine)
                .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
                .where(ChangeAssessment.change_id.in_(change_ids),
                       AssessmentCostLine.plant_id == plant_id)
            )).scalars().all())
            changes = [c for c in changes if c.id in plant_change_ids]
            change_ids = [c.id for c in changes]
            if not changes:
                return []

        effort_rows = (await session.execute(
            select(ChangeAssessment.change_id,
                   func.coalesce(func.sum(ChangeAssessment.effort_hours), 0.0))
            .where(ChangeAssessment.change_id.in_(change_ids),
                   ChangeAssessment.effort_hours.is_not(None))
            .group_by(ChangeAssessment.change_id)
        )).all()
        efforts = {cid: hours for cid, hours in effort_rows}

        project_ids = {c.project_id for c in changes if c.project_id is not None}
        names: dict[int, str] = {}
        if project_ids:
            names = dict((await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )).all())

        rows = []
        for c in changes:
            internal_cost, external_cost = costs.get(c.id, (0.0, 0.0))
            total_cost = internal_cost + external_cost
            revenue = c.quoted_price if c.customer_relevant else c.internal_approved_amount
            margin = None if revenue is None else revenue - total_cost
            margin_pct = (margin / revenue * 100
                          if margin is not None and revenue not in (None, 0) else None)
            rows.append({
                "change_id": c.id,
                "change_number": c.change_number,
                "title": c.title,
                "project_id": c.project_id,
                "project_name": names.get(c.project_id) if c.project_id is not None else None,
                "branch": "customer" if c.customer_relevant else "internal",
                "status": c.status,
                "revenue": _round(revenue),
                "internal_cost": _round(internal_cost),
                "external_cost": _round(external_cost),
                "total_cost": _round(total_cost),
                "margin": _round(margin),
                "margin_pct": _round(margin_pct),
                "effort_hours": _round(efforts.get(c.id, 0.0)),
                "pending_price": revenue is None,
                "realized": c.status in REALIZED_STATUSES,
            })
        return rows

    @staticmethod
    async def summary(
        session: AsyncSession, viewer: Optional[User], *,
        project_id: Optional[int] = None, plant_id: Optional[int] = None,
        branch: Optional[str] = None, status_group: Optional[str] = None,
        date_from: Optional[str] = None, date_to: Optional[str] = None,
    ) -> dict:
        rows = await PnlService.changes_pnl(
            session, viewer, project_id=project_id, plant_id=plant_id,
            branch=branch, status_group=status_group,
            date_from=date_from, date_to=date_to)

        def _agg(subset: list[dict]) -> dict:
            revenue = sum(r["revenue"] or 0.0 for r in subset)
            internal_cost = sum(r["internal_cost"] for r in subset)
            external_cost = sum(r["external_cost"] for r in subset)
            total_cost = sum(r["total_cost"] for r in subset)
            margin = revenue - total_cost
            margin_pct = (margin / revenue * 100) if revenue else None
            return {
                "revenue": _round(revenue),
                "internal_cost": _round(internal_cost),
                "external_cost": _round(external_cost),
                "total_cost": _round(total_cost),
                "margin": _round(margin),
                "margin_pct": _round(margin_pct),
            }

        pipeline_rows = [r for r in rows if r["status"] in PIPELINE_STATUSES]
        realized_rows = [r for r in rows if r["status"] in REALIZED_STATUSES]

        by_project: dict[int, dict] = {}
        for r in rows:
            if r["project_id"] is None:
                continue
            p = by_project.setdefault(r["project_id"], {
                "project_id": r["project_id"], "name": r["project_name"],
                "revenue": 0.0, "total_cost": 0.0,
            })
            p["revenue"] += r["revenue"] or 0.0
            p["total_cost"] += r["total_cost"]
        by_project_list = [
            {**p, "revenue": _round(p["revenue"]), "total_cost": _round(p["total_cost"]),
             "margin": _round(p["revenue"] - p["total_cost"])}
            for p in by_project.values()
        ]

        by_branch = {
            "customer": _agg([r for r in rows if r["branch"] == "customer"]),
            "internal": _agg([r for r in rows if r["branch"] == "internal"]),
        }

        return {
            "totals": _agg(rows),
            "pipeline": _agg(pipeline_rows),
            "realized": _agg(realized_rows),
            "by_project": by_project_list,
            "by_branch": by_branch,
            "count": len(rows),
        }
