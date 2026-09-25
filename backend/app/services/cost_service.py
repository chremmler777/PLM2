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
    async def price_for(session: AsyncSession, department_id: int, plant_id: int,
                        on_date=None):
        """The department's effective labour rate at a plant from the cost
        sheet valid on on_date (department_rate only for an org without a
        cost sheet), as a costing_rates.Price (rate None = cannot price)."""
        from app.services import costing_rates
        org_id = await costing_rates.org_id_of_plant(session, plant_id)
        return await costing_rates.labour_price(
            session, org_id, department_id, plant_id, None, on_date)

    @staticmethod
    async def rate_for(session: AsyncSession, department_id: int, plant_id: int,
                       on_date=None) -> Optional[float]:
        return (await CostService.price_for(
            session, department_id, plant_id, on_date)).rate

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
        price = await CostService.price_for(
            session, assessment.department_id, plant_id)
        # No rate in the cost sheet: the line says so (None), it is not 0,
        # and it names no source it did not come from.
        rate = price.rate
        source = price.source if rate is not None else None

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
                currency=price.currency, rate_source=source,
                cost_sheet_version_id=price.version_id if rate is not None else None,
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
            new_value={"assessment_id": assessment.id, "lines": len(seeded)},
            for_department_id=assessment.department_id)
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
    def _pricing_key(plant_id, activity_id, activity_label, cost_kind, demand_hours) -> tuple:
        """What makes a grid line the same line for pricing: an unchanged
        line keeps the rate it was costed with."""
        return (int(plant_id), activity_id, (activity_label or "").strip(),
                cost_kind, round(float(demand_hours or 0.0), 4))

    @staticmethod
    async def replace_cost_lines(session: AsyncSession, change: ChangeRequest,
                                 assessment: ChangeAssessment, lines: list[dict],
                                 user_id: int) -> list[AssessmentCostLine]:
        """Replace the department's grid. A line that comes back unchanged
        (same plant, activity, kind and hours) keeps its rate snapshot, its
        currency and its cost sheet version: saving the grid never re-prices
        what nobody touched. New or changed lines are priced from the cost
        sheet valid today; a line with hours and no rate is refused."""
        from app.services.change_service import ChangeService  # local import avoids cycle
        await session.refresh(assessment, ["cost_lines"])
        kept: dict[tuple, list[AssessmentCostLine]] = {}
        for old in assessment.cost_lines:
            if old.rate_snapshot is None:
                continue          # never priced: price it now
            kept.setdefault(CostService._pricing_key(
                old.plant_id, old.activity_id, old.activity_label, old.cost_kind,
                old.demand_hours), []).append(old)
        snapshots: dict[tuple, list[tuple]] = {
            k: [(o.rate_snapshot, o.currency, o.rate_source, o.cost_sheet_version_id)
                for o in v] for k, v in kept.items()}
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
            key = CostService._pricing_key(
                plant_id, spec.get("activity_id"), spec.get("activity_label"),
                cost_kind, demand_hours)
            if snapshots.get(key):
                rate, currency, source, version_id = snapshots[key].pop(0)
            else:
                price = await CostService.price_for(
                    session, assessment.department_id, plant_id)
                if price.rate is None and demand_hours > 0:
                    # Cannot price: refused, never valued at 0.
                    raise CostError(
                        f"No rate in the cost sheet for department "
                        f"{assessment.department_id} at plant {plant_id}")
                rate, currency = price.rate, price.currency
                source = price.source if rate is not None else None
                version_id = price.version_id if rate is not None else None
            line = AssessmentCostLine(
                assessment_id=assessment.id, plant_id=plant_id,
                activity_id=spec.get("activity_id"), activity_label=spec.get("activity_label"),
                cost_kind=cost_kind, demand_hours=demand_hours, rate_snapshot=rate,
                internal_cost=demand_hours * (rate or 0.0),
                external_cost=float(spec.get("external_cost") or 0.0),
                minutes_per_part=(
                    None if spec.get("minutes_per_part") is None
                    else float(spec["minutes_per_part"])),
                note=spec.get("note"),
                currency=currency, rate_source=source,
                cost_sheet_version_id=version_id,
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
            for_department_id=assessment.department_id,
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

        # Currencies are grouped, never added (spec §15 phase 2, no FX this
        # round): the change's costing currency is its costing plant's; the
        # department margins and the totals carry that currency only, and
        # money in any other currency is reported per currency with a warning.
        from app.models.entities import Plant
        from app.services import cost_sheet_service as cs
        from app.services import costing_rates
        costing_plant = await costing_rates.costing_plant_id(session, change)
        org_id = ((await costing_rates.org_id_of_plant(session, costing_plant))
                  or await costing_rates.change_org_id(session, change))
        currency = await cs.plant_currency(session, costing_plant)
        plant_currency = dict((await session.execute(
            select(Plant.id, Plant.currency))).all())
        by_currency: dict[str, dict] = {}
        unpriced: list[dict] = []
        versions_used: set[int] = set()
        version_ids_used: set[int] = set()

        def _book(cur: str, key: str, amount: float, *buckets) -> None:
            """Money into its currency group; into the margins only in the
            costing currency."""
            if not amount:
                return
            by_currency.setdefault(cur, _blank())[key] += amount
            if cur == currency:
                for b in buckets:
                    b[key] += amount

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
            cur = line.currency or plant_currency.get(line.plant_id) or "EUR"
            if line.cost_sheet_version_id:
                version_ids_used.add(line.cost_sheet_version_id)
            cell = by_cell.setdefault(
                (department_id, line.plant_id),
                {**_blank(), "demand_hours": 0.0, "minutes_per_part": 0.0,
                 "currency": cur})
            # A plant's row and cell are in that plant's currency by nature.
            for bucket in (by_plant.setdefault(
                    line.plant_id, {**_blank(), "currency": cur}), cell):
                bucket[f"{pk}_internal"] += line.internal_cost
                bucket[f"{pk}_external"] += line.external_cost
            dep = by_dep.setdefault(department_id, _blank())
            _book(cur, f"{pk}_internal", line.internal_cost, dep, totals)
            _book(cur, f"{pk}_external", line.external_cost, dep, totals)
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
        # A position's HOURS are money too: the department's own time at the
        # cost sheet's effective labour rate, a machine_time line's hours at
        # the machine class rate, a sampling line's trials at the price of a
        # trial. Read from the rate snapshot stored on the line when it was
        # costed (costing_rates); a line with no rate is NOT counted as 0:
        # it is listed in unpriced_lines and the summation warns.
        pos_by_dep: dict[int, dict] = {}
        book = costing_rates.RateBook(session)
        # The time a department spent on its assessment is its standing
        # internal_effort line (the assessment's own effort_hours for a
        # department that has none).
        effort_from_positions: dict[int, float] = {}
        for p in positions:
            if p.kind == "internal_effort" and p.hours:
                effort_from_positions[p.department_id] = (
                    effort_from_positions.get(p.department_id, 0.0) + float(p.hours))
        for p in positions:
            # The money Sales is quoting, which is the CHOSEN vendor's price
            # once Sales has decided and the department's own effective_cost
            # until then. The recommendation is not overwritten — it travels
            # alongside in the detail below, so a wrap-up can show that the
            # buyer moved the number and by how much.
            cost = p.quoted_cost or 0.0
            line_cur = p.currency or currency
            bucket = ("one_time_external" if p.kind == "external"
                      else "one_time_internal")
            agg = pos_by_dep.setdefault(
                p.department_id,
                {"department_id": p.department_id, "position_cost": 0.0,
                 "hours": 0.0, "hours_cost": 0.0, "machine_hours": 0.0,
                 "trials": 0, "position_count": 0,
                 "unrated_hours": False, "unpriced_count": 0, "positions": []})

            price = await costing_rates.position_price(
                session, change, p, org_id=org_id, plant_id=costing_plant, book=book)
            if price.version_id:
                version_ids_used.add(price.version_id)
            value = costing_rates.line_value(p, price)
            if value is None:
                agg["unrated_hours"] = True
                agg["unpriced_count"] += 1
                unpriced.append({
                    "position_id": p.id, "department_id": p.department_id,
                    "label": p.label, "kind": p.kind,
                    "quantity": costing_rates.quantity(p), "unit": price.unit,
                    "reason": (price.detail.get("missing") or ["rate"])[0],
                    "message": costing_rates.NO_RATE})
                value = 0.0

            # Own time is internal money whatever the position is FOR: the
            # hours a department spends specifying and chasing a supplier are
            # ours, not the supplier's.
            dep = by_dep.setdefault(p.department_id, _blank())
            _book(line_cur, bucket, cost, dep, totals)
            _book(price.currency, "one_time_internal", value, dep, totals)

            if p.kind == "machine_time":
                agg["machine_hours"] += float(p.hours or 0.0)
            elif p.kind == "sampling":
                agg["trials"] += int(p.trials or 0)
            else:
                agg["hours"] += float(p.hours or 0.0)
            if line_cur == currency:
                agg["position_cost"] += cost
            if price.currency == currency:
                agg["hours_cost"] += value
            agg["position_count"] += 1
            # Both sides of the vendor decision, per position: what the
            # department recommended and what Sales bought. The wrap-up line
            # ("recommended: A · chosen: B (reason)") is the only place the
            # divergence is ever seen, so the data for it has to be here and
            # not one join away.
            favorite = p.recommended_offer
            chosen = p.chosen_offer
            agg["positions"].append({
                "position_id": p.id, "label": p.label, "kind": p.kind,
                "cost": cost, "currency": line_cur,
                "line_value": None if price.rate is None and costing_rates.quantity(p)
                else value,
                "rate": price.rate,
                "recommended_vendor": favorite.vendor_name if favorite else None,
                "recommended_cost": favorite.total_cost if favorite else None,
                "chosen_vendor": chosen.vendor_name if chosen else None,
                "chosen_cost": chosen.total_cost if chosen else None,
                "chosen_reason": chosen.chosen_reason if chosen else None,
                "choice_diverges": bool(
                    chosen is not None and favorite is not None
                    and chosen.id != favorite.id),
            })

        totals["grand_total"] = (totals["one_time_internal"] + totals["one_time_external"]
                                 + totals["lifecycle_internal"] + totals["lifecycle_external"])
        for group in by_currency.values():
            group["grand_total"] = (group["one_time_internal"] + group["one_time_external"]
                                    + group["lifecycle_internal"]
                                    + group["lifecycle_external"])
        other_currencies = sorted(c for c in by_currency if c != currency)
        warnings: list[dict] = []
        if other_currencies:
            warnings.append({
                "code": "mixed_currency",
                "message": (f"Costing has amounts in {', '.join(other_currencies)}: "
                            f"they are not in the {currency} totals (no currency "
                            "conversion). See the totals per currency.")})
        if unpriced:
            n = len(unpriced)
            what = ("1 costing line has" if n == 1 else f"{n} costing lines have")
            warnings.append({
                "code": "no_rate",
                "message": (f"{what} no rate in the cost sheet and "
                            f"{'is' if n == 1 else 'are'} not counted: "
                            "the total is too low")})
        if version_ids_used:
            from app.models.cost_sheet import CostSheetVersion
            versions_used = {v for (v,) in (await session.execute(
                select(CostSheetVersion.version).where(
                    CostSheetVersion.id.in_(version_ids_used)))).all()}
        current = await cs.version_on(session, org_id) if org_id is not None else None

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

        effort_hours = {d: float(h) for d, h in efforts}
        effort_hours.update(effort_from_positions)
        efforts = sorted((d, h) for d, h in effort_hours.items() if h)

        by_department = [{"department_id": did, **vals}
                         for did, vals in sorted(by_dep.items())]

        # Stage 9's other half of the same page: what the change was PLANNED to
        # cost is this whole grid, and what it ACTUALLY cost is the booked
        # implementation hours at the departments' current rates. They are read
        # together — a plan-vs-actual card that fetches two endpoints renders
        # half of itself first, and the halves disagree while it does — so the
        # actuals ride on the summation rather than living behind their own
        # roll-up. Additive: every existing key is untouched.
        from app.services.pnl_service import PnlService
        actuals = await PnlService.change_actuals(
            session, change, plan_by_department=by_department)
        revenue_currency = await PnlService.revenue_currency(
            session, change, currency)

        return {
            # Currency (spec §15 phase 2): the totals, by_department and the
            # position margins are in `currency`; every currency's own sums
            # are in totals_by_currency. Nothing is converted.
            "currency": currency,
            # The revenue's currency (the accepted or latest sent offer's,
            # else the costing's): quoted_price is in it. When it is not
            # `currency` there is no margin (no FX).
            "revenue_currency": revenue_currency,
            "totals_by_currency": {c: by_currency[c] for c in sorted(by_currency)},
            "mixed_currency": bool(other_currencies),
            "unpriced_lines": unpriced,
            "warnings": warnings,
            "cost_sheet_versions_used": sorted(versions_used),
            "cost_sheet_current_version": current.version if current else None,
            "by_plant": [{"plant_id": pid, **vals} for pid, vals in sorted(by_plant.items())],
            "by_department": by_department,
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
            # The Tooling Engineer's weight estimate rides along with the
            # costs: it is priced into the same quote, and it is an ESTIMATE
            # until validation weighs the sampled part.
            "part_weight_estimate_g": (
                float(change.estimated_part_weight_g)
                if change.estimated_part_weight_g is not None else None),
            # Booked implementation time priced at today's rates, the plan it
            # is measured against, and the costs that are not hours (quoted
            # scrap, validated weight delta). See PnlService.change_actuals.
            "actuals": actuals,
        }
