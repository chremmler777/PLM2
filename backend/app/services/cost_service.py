"""Cost-line math + Summierung roll-up for the digitized Änderungsmitteilung."""
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest, ChangeAssessment
from app.models.change_cost import (
    AssessmentCostLine, CostingPosition, DepartmentRate, COST_KINDS,
)


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
    async def seed_from_checklist(
        session: AsyncSession, change: ChangeRequest,
        assessment: ChangeAssessment, user_id: int,
    ) -> list:
        """Turn the department's assessment checklist into its starting cost
        grid: one zero-hour line per item it marked impacted, at the current
        rate.

        A department that has already said WHICH items the change touches
        should not then face an empty grid and retype them. Seeded once —
        recorded in the assessment's own details — so re-entering costing
        never duplicates, and a line the department deliberately deleted stays
        deleted.
        """
        details = assessment.details_dict
        if details.get("cost_seeded_at"):
            return []
        impacts = [i for i in (details.get("impacts") or [])
                   if isinstance(i, dict) and i.get("impacted")]
        if not impacts:
            return []

        plant_id = await CostService._costing_plant(session, change)
        if plant_id is None:
            return []      # nothing to price against yet; try again later
        rate = await CostService.rate_for(
            session, assessment.department_id, plant_id) or 0.0

        from app.models.workflow import Department
        from app.services import assessment_checklist as checklist
        dept = await session.get(Department, assessment.department_id)
        dept_name = dept.name if dept is not None else None

        await session.refresh(assessment, ["cost_lines"])
        seeded = []
        for item in impacts:
            key = item.get("key")
            # Checklist items are keyed; the label comes from the definition so
            # the grid reads in the same words the question did. Rows stored
            # before the checklist was fixed still carry their own label.
            label = (checklist.label_for(key, dept_name) if key else None) \
                or item.get("label") or key
            # Cycle time is charged per part for the life of the programme;
            # everything else is a one-off.
            cost_kind = ("lifecycle" if key in checklist.LIFECYCLE_KEYS
                         else "one_time")
            line = AssessmentCostLine(
                assessment_id=assessment.id, plant_id=plant_id,
                activity_id=item.get("activity_id"),
                activity_label=label,
                cost_kind=cost_kind, demand_hours=0.0, rate_snapshot=rate,
                internal_cost=0.0, external_cost=0.0,
                # The remark from the checklist travels with the line: it is
                # the reason this row exists.
                note=item.get("remark") or None,
            )
            session.add(line)
            seeded.append(line)
        details["cost_seeded_at"] = datetime.utcnow().isoformat()
        assessment.details = json.dumps(details)
        await session.flush()
        await session.refresh(assessment, ["cost_lines"])
        from app.services.change_service import ChangeService  # local: cycle
        await ChangeService.append_changelog(
            session, change, "cost_lines_seeded",
            f"Cost grid seeded from the checklist for dept "
            f"{assessment.department_id} ({len(seeded)} lines)", user_id,
            new_value={"assessment_id": assessment.id, "lines": len(seeded)})
        return seeded

    @staticmethod
    async def _costing_plant(session: AsyncSession, change: ChangeRequest):
        """Which plant the seeded lines are priced at: the change's own
        affected plant when it names exactly one, otherwise its project's."""
        plants = list(change.affected_plants or [])
        if len(plants) == 1:
            return plants[0].id
        from app.models.entities import Project
        project = await session.get(Project, change.project_id)
        return project.plant_id if project is not None else None

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
                minutes_per_part=(
                    None if spec.get("minutes_per_part") is None
                    else float(spec["minutes_per_part"])),
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
        # The workbook's actual shape: a department row with a column group per
        # plant. by_plant and by_department are its margins; neither can be
        # derived from the other, so the matrix is its own rollup.
        by_cell: dict[tuple, dict] = {}
        # Per-part minutes roll up by PLANT, not by department: the number that
        # matters is what one part costs on one line, whoever added the time.
        minutes_by_plant: dict[int, float] = {}
        totals = _blank()
        for line, department_id in rows:
            pk = "one_time" if line.cost_kind == "one_time" else "lifecycle"
            cell = by_cell.setdefault(
                (department_id, line.plant_id),
                {**_blank(), "demand_hours": 0.0, "minutes_per_part": 0.0})
            for bucket in (by_plant.setdefault(line.plant_id, _blank()),
                           by_dep.setdefault(department_id, _blank()),
                           cell, totals):
                bucket[f"{pk}_internal"] += line.internal_cost
                bucket[f"{pk}_external"] += line.external_cost
            cell["demand_hours"] += line.demand_hours
            if line.minutes_per_part is not None:
                cell["minutes_per_part"] += line.minutes_per_part
                minutes_by_plant[line.plant_id] = (
                    minutes_by_plant.get(line.plant_id, 0.0) + line.minutes_per_part)

        # Costing positions ADD to the grid; they do not replace it. They carry
        # no plant — an external tool-shop order is not made at a plant — so
        # they land in the department margin and the grand total, and the
        # per-plant matrix stays exactly what the cost lines said. All of them
        # are one-off money: a position priced per part for the life of the
        # programme is a lifecycle cost LINE, which already exists.
        positions = (await session.execute(
            select(CostingPosition).where(
                CostingPosition.change_id == change.id))).scalars().all()
        # A position's HOURS are money too — the assessment time and the
        # implementation support the department declared. Valued exactly the
        # way a cost line values demand_hours: the department's rate at the
        # costing plant. Reporting the hours without the euros left Sales
        # looking at "6 h, €0".
        position_plant = (await CostService._costing_plant(session, change)
                          if positions else None)
        position_rates: dict[int, Optional[float]] = {}
        pos_by_dep: dict[int, dict] = {}
        for p in positions:
            cost = p.effective_cost or 0.0
            bucket = ("one_time_external" if p.kind == "external"
                      else "one_time_internal")
            agg = pos_by_dep.setdefault(
                p.department_id,
                {"department_id": p.department_id, "position_cost": 0.0,
                 "hours": 0.0, "hours_cost": 0.0, "position_count": 0,
                 "unrated_hours": False})

            hours = float(p.hours or 0.0)
            hours_cost = 0.0
            if hours:
                if p.department_id not in position_rates:
                    position_rates[p.department_id] = (
                        await CostService.rate_for(
                            session, p.department_id, position_plant)
                        if position_plant is not None else None)
                rate = position_rates[p.department_id]
                if rate is None:
                    # No rate configured for this department at this plant.
                    # The grid refuses to price hours it has no rate for
                    # rather than inventing one; the roll-up cannot refuse, so
                    # it counts zero and says so. An invented rate would be a
                    # number somebody quotes.
                    agg["unrated_hours"] = True
                else:
                    hours_cost = hours * rate

            # Own time is internal money whatever the position is FOR: the
            # hours a department spends specifying and chasing a supplier are
            # ours, not the supplier's.
            by_dep.setdefault(p.department_id, _blank())[bucket] += cost
            totals[bucket] += cost
            if hours_cost:
                by_dep[p.department_id]["one_time_internal"] += hours_cost
                totals["one_time_internal"] += hours_cost

            agg["position_cost"] += cost
            agg["hours"] += hours
            agg["hours_cost"] += hours_cost
            agg["position_count"] += 1

        totals["grand_total"] = (totals["one_time_internal"] + totals["one_time_external"]
                                 + totals["lifecycle_internal"] + totals["lifecycle_external"])

        # Lead time is the slowest department, not the sum of them: they wait in
        # parallel. Reported per department too, so the long pole is visible
        # rather than just its length.
        lead_rows = (await session.execute(
            select(ChangeAssessment.department_id,
                   ChangeAssessment.lead_time_impact_days)
            .where(ChangeAssessment.change_id == change.id,
                   ChangeAssessment.lead_time_impact_days.is_not(None)))).all()
        # Assessment lead times carry no unit and always meant the calendar,
        # so the whole roll-up is reported in CALENDAR days and anything
        # quoted in working days is converted before it is compared.
        lead_by_dept: dict[int, int] = {}
        for department_id, days in lead_rows:
            lead_by_dept[department_id] = max(lead_by_dept.get(department_id, 0), days)
        # A supplier's delivery date is a lead time like any other — often THE
        # long pole — so the FAVORITE offer's days (or the position's own)
        # count towards the department's, by the same max-not-sum rule. A
        # 5-business-day quote is 7 calendar days and beats a 6-day one.
        for p in positions:
            days = p.effective_lead_time_calendar_days
            if days is not None:
                lead_by_dept[p.department_id] = max(
                    lead_by_dept.get(p.department_id, 0), days)

        efforts = (await session.execute(
            select(ChangeAssessment.department_id,
                   func.coalesce(func.sum(ChangeAssessment.effort_hours), 0.0))
            .where(ChangeAssessment.change_id == change.id,
                   ChangeAssessment.effort_hours.is_not(None))
            .group_by(ChangeAssessment.department_id))).all()

        return {
            "by_plant": [{"plant_id": pid, **vals} for pid, vals in sorted(by_plant.items())],
            "by_department": [{"department_id": did, **vals} for did, vals in sorted(by_dep.items())],
            "by_department_plant": [
                {"department_id": did, "plant_id": pid, **vals}
                for (did, pid), vals in sorted(by_cell.items())],
            "totals": totals,
            "effort_by_department": [
                {"department_id": d, "effort_hours": h} for d, h in sorted(efforts)],
            "total_effort_hours": float(sum(h for _, h in efforts)),
            "lead_time_by_department": [
                {"department_id": d, "lead_time_days": v}
                for d, v in sorted(lead_by_dept.items())],
            "max_lead_time_days": max(lead_by_dept.values(), default=0),
            "lifecycle_minutes_by_plant": [
                {"plant_id": pid, "minutes_per_part": mins}
                for pid, mins in sorted(minutes_by_plant.items())],
            "total_minutes_per_part": float(sum(minutes_by_plant.values())),
            # The position half of the department margin, broken out: the same
            # money is already inside by_department and totals, reported
            # separately so "how much of this is supplier money" is answerable
            # without re-adding it.
            "positions_by_department": [
                pos_by_dep[d] for d in sorted(pos_by_dep)],
            "total_position_cost": float(
                sum(v["position_cost"] for v in pos_by_dep.values())),
            # The valued half of the same rows, so "how much of this is our own
            # time" is answerable without re-multiplying anything.
            "total_position_hours_cost": float(
                sum(v["hours_cost"] for v in pos_by_dep.values())),
        }
