"""Cost-line math + Summierung roll-up for the digitized Änderungsmitteilung."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest, ChangeAssessment
from app.models.change_cost import AssessmentCostLine, DepartmentRate, COST_KINDS


class CostError(ValueError):
    """Invalid cost-line operation; mapped to HTTP 400 in the router."""


class CostService:

    @staticmethod
    async def rate_for(session: AsyncSession, department_id: int, plant_id: int) -> Optional[float]:
        row = (await session.execute(
            select(DepartmentRate).where(
                (DepartmentRate.department_id == department_id)
                & (DepartmentRate.plant_id == plant_id)
            ).order_by(DepartmentRate.effective_from.desc())
        )).scalars().first()
        return row.hourly_rate if row else None

    @staticmethod
    def recompute_assessment_totals(assessment: ChangeAssessment) -> None:
        one_time = sum(l.internal_cost + l.external_cost
                       for l in assessment.cost_lines if l.cost_kind == "one_time")
        lifecycle = sum(l.internal_cost + l.external_cost
                        for l in assessment.cost_lines if l.cost_kind == "lifecycle")
        assessment.cost_impact = one_time
        assessment.lifecycle_cost = lifecycle

    @staticmethod
    async def replace_cost_lines(session: AsyncSession, change: ChangeRequest,
                                 assessment: ChangeAssessment, lines: list[dict],
                                 user_id: int) -> list[AssessmentCostLine]:
        from app.services.change_service import ChangeService  # local import avoids cycle
        await session.refresh(assessment, ["cost_lines"])
        for old in list(assessment.cost_lines):
            await session.delete(old)
        await session.flush()
        new_lines: list[AssessmentCostLine] = []
        for spec in lines:
            cost_kind = spec.get("cost_kind", "one_time")
            if cost_kind not in COST_KINDS:
                raise CostError(f"Invalid cost_kind '{cost_kind}'")
            if spec.get("activity_id") is None and not spec.get("activity_label"):
                raise CostError("Free-input line requires an activity_label")
            plant_id = spec["plant_id"]
            demand_hours = float(spec.get("demand_hours") or 0.0)
            rate = await CostService.rate_for(session, assessment.department_id, plant_id)
            if rate is None and demand_hours > 0:
                raise CostError(
                    f"No rate for department {assessment.department_id} at plant {plant_id}")
            rate = rate or 0.0
            line = AssessmentCostLine(
                assessment_id=assessment.id, plant_id=plant_id,
                activity_id=spec.get("activity_id"), activity_label=spec.get("activity_label"),
                cost_kind=cost_kind, demand_hours=demand_hours, rate_snapshot=rate,
                internal_cost=demand_hours * rate,
                external_cost=float(spec.get("external_cost") or 0.0),
                note=spec.get("note"),
            )
            session.add(line)
            new_lines.append(line)
        await session.flush()
        await session.refresh(assessment, ["cost_lines"])
        CostService.recompute_assessment_totals(assessment)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "cost_lines_updated",
            f"Cost lines updated for dept {assessment.department_id} "
            f"({len(new_lines)} lines)", user_id,
            field_name="cost_impact", new_value=assessment.cost_impact,
        )
        return new_lines

    @staticmethod
    async def summation(session: AsyncSession, change: ChangeRequest) -> dict:
        rows = (await session.execute(
            select(AssessmentCostLine, ChangeAssessment.department_id)
            .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
            .where(ChangeAssessment.change_id == change.id)
        )).all()

        def _blank() -> dict:
            return {"one_time_internal": 0.0, "one_time_external": 0.0,
                    "lifecycle_internal": 0.0, "lifecycle_external": 0.0}

        by_plant: dict[int, dict] = {}
        by_dep: dict[int, dict] = {}
        totals = _blank()
        for line, department_id in rows:
            pk = "one_time" if line.cost_kind == "one_time" else "lifecycle"
            for bucket in (by_plant.setdefault(line.plant_id, _blank()),
                           by_dep.setdefault(department_id, _blank()),
                           totals):
                bucket[f"{pk}_internal"] += line.internal_cost
                bucket[f"{pk}_external"] += line.external_cost
        totals["grand_total"] = (totals["one_time_internal"] + totals["one_time_external"]
                                 + totals["lifecycle_internal"] + totals["lifecycle_external"])
        return {
            "by_plant": [{"plant_id": pid, **vals} for pid, vals in sorted(by_plant.items())],
            "by_department": [{"department_id": did, **vals} for did, vals in sorted(by_dep.items())],
            "totals": totals,
        }
