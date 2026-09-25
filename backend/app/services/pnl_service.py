"""P&L (Profit & Loss) read model: per-change and portfolio-level margin views.

Computed live from change-management data; the only table of its own is
change_actual_costs (supplier invoice lines, migration 091). Revenue is `quoted_price` for customer-relevant changes or
`internal_approved_amount` (the PM-approved summation snapshot) for internal
changes. A row's internal_cost/external_cost/total_cost are the costing's
cost as the summation counts it: the AssessmentCostLine amounts (joined
through ChangeAssessment) plus the costing positions, in the costing
currency. Only changes in status 'costing' or beyond are in scope -
mirrors ReportService's org-scoping via `_org_scope`.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import false as sa_false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentCostLine
from app.models.entities import Project, User
from app.services.report_service import _org_scope

PNL_STATUSES = ("costing", "quoting", "quoted", "approved", "in_implementation",
                "in_validation", "released", "closed")
# Sliced by name, not by index: inserting a status into the tuple must not
# silently move the line between pipeline and realized money.
REALIZED_STATUSES = PNL_STATUSES[PNL_STATUSES.index("approved"):]
# Money that is still an offer, not a commitment — 'quoting' is the same kind
# of not-yet as 'quoted', one step earlier.
PIPELINE_STATUSES = ("costing", "quoting", "quoted")


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
        # Revenue and margin are prices: only the changes the viewer may read
        # prices for (price_redaction.PriceViewer) are in their P&L.
        from app.services.price_redaction import price_scope
        stmt = await price_scope(session, viewer, stmt)
        changes = (await session.execute(stmt)).scalars().all()
        if not changes:
            return []
        change_ids = [c.id for c in changes]

        # Single grouped cost query across every change in scope - never call
        # CostService.summation per change (N+1 query trap). Grouped by the
        # line's currency too: amounts in different currencies are never
        # added (spec §15 phase 2, no FX).
        from app.models.entities import Plant
        plant_info = {pid: (org, cur or "EUR") for pid, org, cur in (await session.execute(
            select(Plant.id, Plant.organization_id, Plant.currency))).all()}
        cost_rows = (await session.execute(
            select(ChangeAssessment.change_id, AssessmentCostLine.currency,
                   AssessmentCostLine.plant_id,
                   func.coalesce(func.sum(AssessmentCostLine.internal_cost), 0.0),
                   func.coalesce(func.sum(AssessmentCostLine.external_cost), 0.0))
            .select_from(AssessmentCostLine)
            .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
            .where(ChangeAssessment.change_id.in_(change_ids))
            .group_by(ChangeAssessment.change_id, AssessmentCostLine.currency,
                      AssessmentCostLine.plant_id)
        )).all()
        line_costs: dict[int, dict[str, list]] = {}
        for cid, cur, pid, internal, external in cost_rows:
            cur = cur or (plant_info.get(pid) or (None, "EUR"))[1]
            bucket = line_costs.setdefault(cid, {}).setdefault(cur, [0.0, 0.0])
            bucket[0] += internal or 0.0
            bucket[1] += external or 0.0

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

        ctx = await PnlService._portfolio_context(session, changes, plant_info)
        costs: dict[int, tuple[float, float]] = {}
        other_cost: dict[int, dict[str, float]] = {}
        for c in changes:
            cur = ctx["currency"][c.id]
            by_cur = line_costs.get(c.id, {})
            internal, external = by_cur.get(cur, (0.0, 0.0))
            costs[c.id] = (internal, external)
            others = {k: _round(v[0] + v[1]) for k, v in by_cur.items()
                      if k != cur and (v[0] or v[1])}
            if others:
                other_cost[c.id] = others
        ova = await PnlService._offer_vs_actual_batch(session, changes, costs, ctx)

        rows = []
        for c in changes:
            currency = ctx["currency"][c.id]
            o = ova.get(c.id, {})
            revenue_currency = o.get("revenue_currency") or currency
            comparable = revenue_currency == currency
            # The row's cost is the costing's, as the summation counts it:
            # the assessment cost lines plus the costing positions (quoted
            # cost by kind, own hours at the rate), in the costing currency.
            internal_cost, external_cost = costs.get(c.id, (0.0, 0.0))
            pi, pe = o.get("position_cost") or (0.0, 0.0)
            internal_cost += pi
            external_cost += pe
            total_cost = internal_cost + external_cost
            revenue = c.quoted_price if c.customer_relevant else c.internal_approved_amount
            margin = (None if revenue is None or not comparable
                      else revenue - total_cost)
            margin_pct = (margin / revenue * 100
                          if margin is not None and revenue not in (None, 0) else None)
            warnings = list(o.get("warnings") or [])
            if c.id in other_cost:
                warnings.append({
                    "code": "mixed_currency",
                    "message": (f"Costing has amounts in {', '.join(other_cost[c.id])}: "
                                f"not in the {currency} cost (no currency conversion)")})
            rows.append({
                "change_id": c.id,
                "change_number": c.change_number,
                "title": c.title,
                "project_id": c.project_id,
                "project_name": names.get(c.project_id) if c.project_id is not None else None,
                "branch": "customer" if c.customer_relevant else "internal",
                "status": c.status,
                # Every amount of the row is in `currency` (the costing
                # plant's) except the revenue, which is in revenue_currency;
                # when the two differ no margin is computed (no FX).
                "currency": currency,
                "revenue_currency": revenue_currency,
                "currency_mismatch": not comparable,
                "other_currency_cost": other_cost.get(c.id, {}),
                "revenue": _round(revenue),
                "internal_cost": _round(internal_cost),
                "external_cost": _round(external_cost),
                "total_cost": _round(total_cost),
                "margin": _round(margin),
                "margin_pct": _round(margin_pct),
                "effort_hours": _round(efforts.get(c.id, 0.0)),
                "pending_price": revenue is None,
                "realized": c.status in REALIZED_STATUSES,
                # offer versus doing (spec §13)
                **{k: v for k, v in o.items()
                   if k not in ("warnings", "revenue_currency", "position_cost")},
                "no_rate": bool(o.get("no_rate")),
                "warnings": warnings,
            })
        return rows

    @staticmethod
    async def _portfolio_context(session, changes, plant_info: dict) -> dict:
        """Per change of the list: its costing plant, organisation and
        currency, resolved with two grouped queries, plus the request's
        RateBook (each organisation's cost sheet loaded once)."""
        from app.models.change import change_affected_plants
        from app.services import costing_rates
        ids = [c.id for c in changes]
        plants: dict[int, list] = {}
        for cid, pid in (await session.execute(
                select(change_affected_plants.c.change_id,
                       change_affected_plants.c.plant_id)
                .where(change_affected_plants.c.change_id.in_(ids)))).all():
            plants.setdefault(cid, []).append(pid)
        project_ids = {c.project_id for c in changes if c.project_id}
        project_plant = dict((await session.execute(
            select(Project.id, Project.plant_id).where(Project.id.in_(project_ids))
        )).all()) if project_ids else {}
        plant_of, org_of, currency = {}, {}, {}
        for c in changes:
            ps = plants.get(c.id) or []
            pid = ps[0] if len(ps) == 1 else project_plant.get(c.project_id)
            plant_of[c.id] = pid
            org, cur = plant_info.get(pid, (None, "EUR"))
            if org is None:
                org = plant_info.get(project_plant.get(c.project_id), (None, None))[0]
            org_of[c.id] = org
            currency[c.id] = cur if pid is not None else "EUR"
        return {"plant": plant_of, "org": org_of, "currency": currency,
                "book": costing_rates.RateBook(session)}

    @staticmethod
    async def _offer_vs_actual_batch(session, changes, costs: dict,
                                     ctx: Optional[dict] = None) -> dict[int, dict]:
        """The list's offer-vs-actual columns, a fixed number of grouped
        queries for the whole portfolio (the card's per-change version would
        be an N+1 across it): cost sheet versions are loaded once per
        organisation and picked by date in Python (RateBook). Planned figures
        come from the accepted offer's frozen snapshot; without one the offer
        total (or quoted price) and the cost lines stand in. Money in another
        currency than the costing's is left out, and a revenue in another
        currency gets no margin (no FX)."""
        from app.models.change_impl import ImplementationBooking
        from app.models.change_offer import ChangeOffer
        from app.models.change_plan import ChangePlanTask
        from app.services.change_plan_service import ChangePlanService
        from app.services.offer_service import SNAPSHOT_KEY
        from app.services import costing_rates
        if ctx is None:
            from app.models.entities import Plant
            plant_info = {pid: (org, cur or "EUR") for pid, org, cur in (await session.execute(
                select(Plant.id, Plant.organization_id, Plant.currency))).all()}
            ctx = await PnlService._portfolio_context(session, changes, plant_info)
        book = ctx["book"]
        ids = [c.id for c in changes]
        offers = list((await session.execute(
            select(ChangeOffer).where(
                ChangeOffer.change_id.in_(ids),
                ChangeOffer.status.in_(("sent", "accepted"))))).scalars().all())
        by_change: dict[int, ChangeOffer] = {}
        for o in sorted(offers, key=lambda o: o.version):
            by_change[o.change_id] = o            # latest sent/accepted
        for o in offers:
            if o.status == "accepted":
                by_change[o.change_id] = o        # the accepted one wins

        # booked hours x the rate valid on each booking's date (spec §15
        # phase 2), at the change's rate plant
        booked = list((await session.execute(
            select(ImplementationBooking)
            .where(ImplementationBooking.change_id.in_(ids))
            .order_by(ImplementationBooking.id))).scalars().all())
        by_id = {c.id: c for c in changes}
        internal_actual: dict[int, float] = {}
        bookings_by_change: dict[int, list] = {}
        for b in booked:
            bookings_by_change.setdefault(b.change_id, []).append(b)
        for cid, rows in bookings_by_change.items():
            cur = ctx["currency"][cid]
            for row in await costing_rates.price_bookings(
                    session, by_id[cid], rows, plant_id=ctx["plant"][cid],
                    org_id=ctx["org"][cid], book=book):
                # unpriced hours count nothing here; the card warns. Hours
                # priced in another currency stay out (no FX).
                value = 0.0
                if row["labour_value"] and row["labour_currency"] == cur:
                    value += row["labour_value"]
                if row["machine_value"] and row["machine_currency"] == cur:
                    value += row["machine_value"]
                if row["hours"] or row["machine_hours"]:
                    internal_actual[cid] = internal_actual.get(cid, 0.0) + value

        # costing positions belong to the plan exactly as in the summation:
        # quoted cost by kind, their own hours at the rate snapshot (priced
        # live, from the same book, where there is none)
        from app.models.change_cost import CostingPosition
        pos_cost: dict[int, list] = {}
        no_rate: set[int] = set()
        tonnage: Optional[dict[int, float]] = None

        async def change_class(c) -> Optional[int]:
            """The change's own class, else its tonnage default: one grouped
            query for every change, the classes from the book."""
            nonlocal tonnage
            if getattr(c, "machine_class_id", None):
                return c.machine_class_id
            if tonnage is None:
                from app.models.change import ChangeImpactedItem
                from app.models.part import Part
                tonnage = {cid: t for cid, t in (await session.execute(
                    select(ChangeImpactedItem.change_id, func.max(Part.tool_tonnage_class))
                    .join(Part, Part.id == ChangeImpactedItem.part_id)
                    .where(ChangeImpactedItem.change_id.in_(ids),
                           Part.tool_tonnage_class.is_not(None))
                    .group_by(ChangeImpactedItem.change_id))).all()}
            return await book.class_for_tonnage(ctx["org"][c.id], tonnage.get(c.id))
        for p in (await session.execute(select(CostingPosition).where(
                CostingPosition.change_id.in_(ids)))).scalars().all():
            cid = p.change_id
            cur = ctx["currency"][cid]
            bucket = pos_cost.setdefault(cid, [0.0, 0.0])
            if (p.currency or cur) == cur:
                bucket[1 if p.kind == "external" else 0] += float(p.quoted_cost or 0.0)
            price = costing_rates.stored_price(p)
            if price is None and costing_rates.quantity(p):
                if p.kind in ("machine_time", "sampling"):
                    cls = p.machine_class_id or await change_class(by_id[cid])
                    fn = book.machine_price if p.kind == "machine_time" else book.sampling_price
                    price = await fn(ctx["org"][cid], cls, ctx["plant"][cid])
                else:
                    price = await book.labour_price(ctx["org"][cid], p.department_id,
                                                    ctx["plant"][cid], p.labour_position)
            if price is None:
                continue
            value = costing_rates.line_value(p, price)
            if value is None:
                no_rate.add(cid)
            elif price.currency == cur:
                bucket[0] += value

        extra = await PnlService.actual_cost_sums(session, ids)
        issues = await PnlService.issue_costs(session, ids)

        # timing: one query for both plans of every change
        tasks = list((await session.execute(
            select(ChangePlanTask).where(
                ChangePlanTask.change_id.in_(ids),
                ChangePlanTask.is_idea.is_(False)))).scalars().all())
        plan_tasks: dict[tuple, list] = {}
        for t in tasks:
            plan_tasks.setdefault((t.change_id, t.plan), []).append(t)

        internal_frozen = await PnlService.internal_frozen(
            session, [c.id for c in changes if not c.customer_relevant])
        out = {}
        for c in changes:
            currency = ctx["currency"][c.id]
            o = by_change.get(c.id)
            snap = (((o.data or {}).get(SNAPSHOT_KEY) or {}).get("pnl")
                    if o is not None and o.status == "accepted" else None)
            if snap is None and o is None and not c.customer_relevant:
                snap = internal_frozen.get(c.id)
            internal_cost, external_cost = costs.get(c.id, (0.0, 0.0))
            mother_plant = getattr(c, "origin", None) == "mother_plant"
            revenue_currency = currency
            if mother_plant:
                # spec §14: no offer basis, actual local costs only
                planned = {"revenue": None, "internal": 0.0, "external": 0.0,
                           "scrap": 0.0}
            elif snap:
                planned = {k: snap.get(k) for k in
                           ("revenue", "internal", "external", "scrap")}
                revenue_currency = snap.get("currency") or (
                    o.currency if o is not None else None) or currency
            else:
                revenue = (o.total_one_time if o is not None else
                           c.quoted_price if c.customer_relevant
                           else c.internal_approved_amount)
                if o is not None:
                    revenue_currency = o.currency or currency
                pi, pe = pos_cost.get(c.id, (0.0, 0.0))
                planned = {"revenue": revenue, "internal": internal_cost + pi,
                           "external": external_cost + pe, "scrap": 0.0}
            comparable = revenue_currency == currency
            e = extra.get(c.id, {})
            i = issues.get(c.id, {})
            fig = compose(planned, {
                "revenue": (None if planned["revenue"] is None else
                            planned["revenue"] + i.get("customer_quoted", 0.0)),
                "internal": internal_actual.get(c.id, 0.0),
                "external": e.get("external", 0.0), "scrap": e.get("scrap", 0.0),
                "other": e.get("other", 0.0),
                "issues_internal": i.get("internal", 0.0),
                "issues_customer": i.get("customer", 0.0),
                "issues_supplier": i.get("supplier", 0.0)},
                in_progress=c.status in IN_PROGRESS_STATUSES)
            if not comparable:
                for k in ("planned_margin", "actual_margin", "forecast_margin",
                          "variance"):
                    fig[k] = None
            # nothing booked, invoiced or raised yet: there is no actual to
            # compare, and a zero would read as a saving
            recorded = (c.id in internal_actual or bool(e) or bool(i))
            phase = pnl_phase(c, recorded)

            # slip against the detailed baseline, else the offered finish
            detailed = plan_tasks.get((c.id, "detailed"), [])
            cal = ChangePlanService.calendar(c, "detailed")
            ChangePlanService._attach(detailed, cal)
            baseline = max((t.baseline_finish for t in detailed if t.baseline_finish),
                           default=None)
            if baseline is None and snap and snap.get("quote_finish"):
                baseline = date.fromisoformat(snap["quote_finish"])
            if baseline is None:
                quote = plan_tasks.get((c.id, "quote"), [])
                ChangePlanService._attach(quote, ChangePlanService.calendar(c, "quote"))
                baseline = max((t.end_date for t in quote), default=None)
            forecast = max((t.end_date for t in detailed), default=None)
            slip = (cal.idx(forecast) - cal.idx(baseline)
                    if baseline is not None and forecast is not None else None)
            warnings = []
            if not comparable:
                warnings.append({
                    "code": "currency_mismatch",
                    "message": (f"The revenue is in {revenue_currency}, the costing in "
                                f"{currency}: no margin without a currency conversion")})
            if c.id in no_rate:
                warnings.append({"code": "no_rate", "message": costing_rates.NO_RATE_WARNING})
            out[c.id] = {
                "phase": phase,
                # the card's basis rule (pnl_basis), so list and card agree
                "basis": pnl_basis(c, o, bool(snap)),
                "revenue_currency": revenue_currency,
                "offer_revenue": fig["planned_revenue"],
                "planned_cost": fig["planned_cost"],
                "planned_margin": fig["planned_margin"],
                "actual_revenue": fig["actual_revenue"] if phase == "actual" else None,
                "actual_cost": fig["actual_cost"] if phase == "actual" else None,
                "actual_margin": fig["actual_margin"] if phase == "actual" else None,
                "forecast_cost": fig["forecast_cost"] if phase == "actual" else None,
                "forecast_margin": fig["forecast_margin"] if phase == "actual" else None,
                "variance": fig["variance"] if phase == "actual" else None,
                "slip_days": slip,
                "slip_unit": "working days" if cal.working else "calendar days",
                "no_rate": c.id in no_rate,
                "warnings": warnings,
                # (internal, external) of the costing positions, for the
                # row's own cost columns; not a field of the row itself
                "position_cost": tuple(pos_cost.get(c.id, (0.0, 0.0))),
            }
        return out

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
            # Rows whose revenue is in another currency than their costing
            # have no margin (no FX): their revenue stays out of every sum,
            # and so does their cost where it would meet that revenue.
            comparable = [r for r in subset if not r.get("currency_mismatch")]
            revenue = sum(r["revenue"] or 0.0 for r in comparable)
            internal_cost = sum(r["internal_cost"] for r in subset)
            external_cost = sum(r["external_cost"] for r in subset)
            total_cost = sum(r["total_cost"] for r in subset)
            margin = revenue - sum(r["total_cost"] for r in comparable)
            margin_pct = (margin / revenue * 100) if revenue else None
            # Offer vs doing: revenue, cost and margin over the SAME rows,
            # the priced ones (a change without a price has no margin, so its
            # cost stays out of the cost too); the rest is counted.
            priced = [r for r in comparable if r.get("offer_revenue") is not None]
            actual_rows = [r for r in priced if r.get("phase") == "actual"]
            slips = [r["slip_days"] for r in subset if r.get("slip_days") is not None]
            return {
                "offer_revenue": _round(sum(r["offer_revenue"] for r in priced)),
                "planned_cost": _round(sum(r.get("planned_cost") or 0.0 for r in priced)),
                "planned_margin": _round(sum(r.get("planned_margin") or 0.0 for r in priced)),
                "priced_count": len(priced),
                "unpriced_count": len(comparable) - len(priced),
                "mismatch_count": len(subset) - len(comparable),
                "no_rate_count": sum(1 for r in subset if r.get("no_rate")),
                "actual_revenue": _round(sum(r.get("actual_revenue") or 0.0
                                             for r in actual_rows)),
                "actual_cost": _round(sum(r.get("actual_cost") or 0.0 for r in actual_rows)),
                "actual_margin": _round(sum(r.get("actual_margin") or 0.0 for r in actual_rows)),
                "forecast_cost": _round(sum(r.get("forecast_cost") or 0.0
                                            for r in actual_rows)),
                "forecast_margin": _round(sum(r.get("forecast_margin") or 0.0 for r in actual_rows)),
                "actual_count": len(actual_rows),
                "variance": _round(sum(r.get("variance") or 0.0 for r in actual_rows)),
                "late_count": sum(1 for x in slips if x > 0),
                "max_slip_days": max(slips, default=None),
                "revenue": _round(revenue),
                "internal_cost": _round(internal_cost),
                "external_cost": _round(external_cost),
                "total_cost": _round(total_cost),
                "margin": _round(margin),
                "margin_pct": _round(margin_pct),
            }

        def _block(subset: list[dict]) -> dict:
            pipeline_rows = [r for r in subset if r["status"] in PIPELINE_STATUSES]
            realized_rows = [r for r in subset if r["status"] in REALIZED_STATUSES]
            by_project: dict[int, dict] = {}
            for r in subset:
                if r["project_id"] is None:
                    continue
                p = by_project.setdefault(r["project_id"], {
                    "project_id": r["project_id"], "name": r["project_name"],
                    "revenue": 0.0, "total_cost": 0.0, "margin_cost": 0.0,
                })
                p["total_cost"] += r["total_cost"]
                if not r.get("currency_mismatch"):
                    p["revenue"] += r["revenue"] or 0.0
                    p["margin_cost"] += r["total_cost"]
            return {
                "totals": _agg(subset),
                "pipeline": _agg(pipeline_rows),
                "realized": _agg(realized_rows),
                "by_project": [
                    {"project_id": p["project_id"], "name": p["name"],
                     "revenue": _round(p["revenue"]), "total_cost": _round(p["total_cost"]),
                     "margin": _round(p["revenue"] - p["margin_cost"])}
                    for p in by_project.values()],
                "by_branch": {
                    "customer": _agg([r for r in subset if r["branch"] == "customer"]),
                    "internal": _agg([r for r in subset if r["branch"] == "internal"]),
                },
                "count": len(subset),
            }

        # Currencies are grouped, never added (spec §15 phase 2): one block
        # per costing currency. The top level is the block of the currency
        # most changes are costed in, so a single-currency portfolio reads
        # exactly as before.
        groups: dict[str, list[dict]] = {}
        for r in rows:
            groups.setdefault(r.get("currency") or "EUR", []).append(r)
        currencies = sorted(groups, key=lambda c: (-len(groups[c]), c))
        by_currency = {c: _block(groups[c]) for c in sorted(groups)}
        primary = currencies[0] if currencies else "EUR"
        top = by_currency.get(primary) or _block([])
        return {
            **top,
            "count": len(rows),
            "currency": primary,
            "currencies": currencies,
            "by_currency": by_currency,
        }

    # ------------------------------------------------------------------
    # Stage 9: plan versus actual, for one change
    # ------------------------------------------------------------------
    # Additive and per-change on purpose. The portfolio rows above stay exactly
    # what they were — they are a grouped query over every change in scope, and
    # pricing booked hours per department inside them would be an N+1 across
    # the whole portfolio for a number only one change's own P&L card asks for.
    #
    # Served ON THE SUMMATION (CostService.summation calls this and hangs the
    # result under 'actuals'), because plan and actual are read together or not
    # at all: a plan-vs-actual card that has to fetch two endpoints will render
    # half of itself first, and the halves will disagree while it does.
    @staticmethod
    async def _rate_plant(session: AsyncSession, change) -> Optional[int]:
        """Which plant's rates value the booked hours: the change's own
        affected plant when it names exactly one, otherwise its project's.

        The same rule as CostService._costing_plant, asked in SQL rather than
        through change.affected_plants. This runs on every summation, and a
        summation is called with hand-built ChangeRequest objects whose
        relationships were never loaded; touching one there is a lazy load in
        async context, which is a MissingGreenlet rather than a query.
        """
        from app.models.change import change_affected_plants
        plants = (await session.execute(
            select(change_affected_plants.c.plant_id).where(
                change_affected_plants.c.change_id == change.id))).scalars().all()
        if len(plants) == 1:
            return plants[0]
        if change.project_id is None:
            return None
        return (await session.execute(
            select(Project.plant_id).where(
                Project.id == change.project_id))).scalar_one_or_none()

    @staticmethod
    async def change_actuals(
        session: AsyncSession, change, *,
        plan_by_department: Optional[list[dict]] = None,
    ) -> dict:
        """What the change actually cost us, against what it was priced at.

        The actual cost is booked hours × the department's CURRENT rate,
        deliberately not a rate frozen onto the booking: the plan side (the
        cost lines) values hours the same way, and two different rates would
        make the comparison meaningless. A department with no rate configured
        at the costing plant is reported `unrated` and counted at zero — the
        summation makes the same call, because an invented rate is a number
        somebody quotes.

        extras are the money that is not hours: the scrap the customer was
        quoted for a planned-scrap changeover, and — as a delta, never as a
        made-up euro amount — a validated part weight that missed the
        estimate. What a gram is worth on this part is a negotiation, not
        arithmetic this service is entitled to do.

        plan_by_department is the summation's own roll-up, passed in by the
        caller that already computed it so this never recurses into it.
        """
        from app.models.workflow import Department
        from app.services.implementation_service import ImplementationService
        from app.services.validation_service import ValidationService

        from app.models.change_impl import ImplementationBooking
        from app.services import cost_sheet_service as cs
        from app.services import costing_rates
        implementing = await ImplementationService.implementing_department_ids(
            session, change)
        plant_id = await PnlService._rate_plant(session, change)
        org_id = ((await costing_rates.org_id_of_plant(session, plant_id))
                  or await costing_rates.change_org_id(session, change))
        currency = await cs.plant_currency(session, plant_id)
        plan_by_dept = {row["department_id"]: row
                        for row in (plan_by_department or [])}
        names = dict((await session.execute(
            select(Department.id, Department.name))).all())
        # Every booking priced on its own date (spec §15 phase 2): the rate
        # valid when the hours were worked, the booking's position if it
        # names one, machine hours at the machine class rate.
        bookings = list((await session.execute(
            select(ImplementationBooking).where(
                ImplementationBooking.change_id == change.id)
            .order_by(ImplementationBooking.id))).scalars().all())
        priced = await costing_rates.price_bookings(
            session, change, bookings, org_id=org_id, plant_id=plant_id)
        per_dept: dict[int, dict] = {}
        other_currency: dict[str, float] = {}
        for row in priced:
            d = per_dept.setdefault(row["department_id"], {
                "hours": 0.0, "cost": 0.0, "rates": set(), "unrated": False,
                "machine_hours": 0.0, "machine_cost": 0.0, "machine_unrated": False})
            d["hours"] += row["hours"]
            d["machine_hours"] += row["machine_hours"]
            if row["labour_value"] is None:
                d["unrated"] = True
            elif row["labour_currency"] != currency:
                other_currency[row["labour_currency"]] = (
                    other_currency.get(row["labour_currency"], 0.0) + row["labour_value"])
            else:
                d["cost"] += row["labour_value"]
                if row["labour_rate"] is not None:
                    d["rates"].add(row["labour_rate"])
            if row["machine_value"] is None:
                d["machine_unrated"] = True
            elif row["machine_hours"] and row["machine_currency"] != currency:
                other_currency[row["machine_currency"]] = (
                    other_currency.get(row["machine_currency"], 0.0) + row["machine_value"])
            else:
                d["machine_cost"] += row["machine_value"]

        departments = []
        for dept_id in sorted(set(implementing) | set(per_dept)):
            d = per_dept.get(dept_id) or {
                "hours": 0.0, "cost": 0.0, "rates": set(), "unrated": False,
                "machine_hours": 0.0, "machine_cost": 0.0, "machine_unrated": False}
            hours = d["hours"]
            rate = None
            if len(d["rates"]) == 1:
                rate = next(iter(d["rates"]))
            elif not d["rates"] and not hours:
                # nothing booked yet: show the rate that would apply today
                rate = (await costing_rates.labour_price(
                    session, org_id, dept_id, plant_id)).rate
            plan = plan_by_dept.get(dept_id) or {}
            plan_cost = (plan.get("one_time_internal", 0.0)
                         + plan.get("one_time_external", 0.0)
                         + plan.get("lifecycle_internal", 0.0)
                         + plan.get("lifecycle_external", 0.0))
            actual = d["cost"] + d["machine_cost"]
            departments.append({
                "department_id": dept_id,
                "department_name": names.get(dept_id),
                "booked_hours": _round(hours),
                # One rate when every booking was priced alike; None when
                # the rate changed between bookings (rates lists them).
                "hourly_rate": rate,
                "rates": sorted(d["rates"]),
                "machine_hours": _round(d["machine_hours"]),
                "machine_cost": _round(d["machine_cost"]),
                "actual_cost": _round(actual),
                "plan_cost": _round(plan_cost),
                "variance": _round(actual - plan_cost),
                # True when hours were booked that the cost sheet has no rate
                # for (on their booking date): actual_cost is then a floor,
                # not a total, and the card must say so.
                "unrated": bool(d["unrated"] or d["machine_unrated"]),
            })

        extras = []
        if change.bank_build_mode == "planned_scrap":
            extras.append({
                "key": "scrap_quote",
                "label": "Planned scrap quoted to the customer",
                "amount": (_round(float(change.scrap_quote_price))
                           if change.scrap_quote_price is not None else None),
            })
        weight_delta = ValidationService.weight_delta(change)
        if weight_delta:
            extras.append({
                "key": "weight_delta",
                "label": f"Validated part weight is {weight_delta:+g} g against "
                         "the estimate the quote was built on",
                # No euros: what a gram is worth here is Sales' negotiation.
                "amount": None,
                "delta_g": weight_delta,
                "acknowledged": change.weight_delta_ack_at is not None,
            })

        total_actual = sum(d["actual_cost"] for d in departments)
        total_plan = sum(d["plan_cost"] for d in departments)
        return {
            "departments": departments,
            "extras": extras,
            "total_actual": _round(total_actual),
            "total_plan": _round(total_plan),
            "total_booked_hours": _round(
                sum(d["booked_hours"] for d in departments)),
            "total_extras": _round(sum(e["amount"] or 0.0 for e in extras)),
            "unrated_hours": any(d["unrated"] for d in departments),
            "rate_plant_id": plant_id,
            "currency": currency,
            # Priced amounts in another currency than the plant's: not in
            # the totals, never converted.
            "other_currency": {k: _round(v) for k, v in sorted(other_currency.items())},
            "total_machine_hours": _round(
                sum(d["machine_hours"] for d in departments)),
            "variance": _round(total_actual - total_plan),
        }

    # ------------------------------------------------------------------
    # Offer versus doing (spec §13): what we offered and planned when the
    # customer said yes, against what the change really cost.
    # ------------------------------------------------------------------
    @staticmethod
    async def planned_figures(session: AsyncSession, change, offer=None) -> dict:
        """The plan side as it stands NOW: revenue from the offer (or the
        internal approval), internal and external cost from the costing
        summation, scrap from the offer's changeover. Frozen into the accepted
        offer's `_snapshot.pnl` at acceptance (OfferService.freeze_pnl); read
        live only for changes that have no frozen plan."""
        from app.services.cost_service import CostService
        from app.services.offer_service import compute_totals, normalise
        summ = await CostService.summation(session, change)
        t = summ["totals"]
        internal = float(t["one_time_internal"] + t["lifecycle_internal"])
        external = float(t["one_time_external"] + t["lifecycle_external"])
        revenue = scrap = None
        piece = None
        currency = summ.get("currency") or "EUR"
        if offer is not None:
            data = normalise(offer.data)
            totals = compute_totals(data, internal + external)
            revenue = float(offer.total_one_time
                            if offer.total_one_time is not None
                            else totals["total_one_time"])
            scrap = float(totals["scrap"] or 0.0)
            currency = offer.currency or "EUR"
            if totals.get("piece_price_delta") is not None:
                piece = {
                    "delta_per_piece": totals["piece_price_delta"],
                    "annual_volume": _num_or_none(
                        (data.get("piece_price") or {}).get("annual_volume")),
                    "annual_effect": totals["annual_effect"],
                }
        elif change.customer_relevant:
            revenue = change.quoted_price
        else:
            revenue = change.internal_approved_amount
        if scrap is None:
            scrap = (float(change.scrap_quote_price)
                     if change.bank_build_mode == "planned_scrap"
                     and change.scrap_quote_price is not None else 0.0)
        quote_finish = await PnlService._plan_finish(session, change, "quote")
        return {
            "taken_at": datetime.utcnow().isoformat(),
            "currency": currency,
            # what the costing was in and which cost sheet priced it, frozen
            # with the plan (spec §15 phase 2)
            "costing_currency": summ.get("currency"),
            "cost_sheet_versions": summ.get("cost_sheet_versions_used"),
            "offer_version": offer.version if offer is not None else None,
            "revenue": _round(revenue),
            "internal": _round(internal),
            "external": _round(external),
            "scrap": _round(scrap),
            "piece_price": piece,
            # the finish the customer was offered: the timing baseline until
            # the detailed plan has its own
            "quote_finish": quote_finish.isoformat() if quote_finish else None,
        }

    @staticmethod
    async def internal_frozen(session, change_ids) -> dict[int, dict]:
        """{change_id: pnl} frozen at internal approval (the latest
        'pnl_frozen' changelog row per change)."""
        import json as _json
        from app.models.change import ChangeChangelog
        ids = list(change_ids)
        if not ids:
            return {}
        out: dict[int, dict] = {}
        for cid, raw in (await session.execute(
                select(ChangeChangelog.change_id, ChangeChangelog.new_value)
                .where(ChangeChangelog.change_id.in_(ids),
                       ChangeChangelog.action == "pnl_frozen")
                .order_by(ChangeChangelog.id))).all():
            try:
                pnl = (_json.loads(raw) or {}).get("pnl")
            except (TypeError, ValueError):
                pnl = None
            if pnl:
                out[cid] = pnl
        return out

    @staticmethod
    async def _plan_finish(session, change, plan: str) -> Optional[date]:
        from app.services.change_plan_service import ChangePlanService
        tasks = [t for t in await ChangePlanService.tasks(session, change, plan)
                 if not t.is_idea]
        return max((t.end_date for t in tasks), default=None)

    @staticmethod
    async def revenue_currency(session, change, costing_currency: str) -> str:
        """The currency the change's revenue (quoted_price) is in: the basis
        offer's, else the costing's (an internal approval, the quoted price
        before any offer, a mother-plant change)."""
        _, offer = await PnlService._basis_offer(session, change)
        return (offer.currency if offer is not None and offer.currency
                else costing_currency)

    @staticmethod
    async def _basis_offer(session, change):
        """(basis, offer): the accepted offer, else the latest sent one. A
        mother-plant change (spec §14) has no offer basis at all: "none"."""
        from app.models.change_offer import ChangeOffer
        from app.services import mother_plants as mp
        if mp.is_mother_plant(change):
            return "none", None
        if change.accepted_offer_id is not None:
            offer = await session.get(ChangeOffer, change.accepted_offer_id)
            if offer is not None:
                return "accepted_offer", offer
        offer = (await session.execute(
            select(ChangeOffer).where(ChangeOffer.change_id == change.id,
                                      ChangeOffer.status.in_(("sent", "accepted")))
            .order_by(ChangeOffer.version.desc()).limit(1))).scalar_one_or_none()
        if offer is not None:
            return ("accepted_offer" if offer.status == "accepted"
                    else "sent_offer"), offer
        if not change.customer_relevant and change.internal_approved_amount is not None:
            return "internal_approval", None
        return "costing", None

    @staticmethod
    async def issue_costs(session, change_ids: list[int]) -> dict[int, dict]:
        """Validation issue extra costs by bearer, per change. The issue table
        arrives with migration 090; before it exists (model not registered)
        every change simply has none."""
        from app.models.database import Base
        out: dict[int, dict] = {}
        tbl = Base.metadata.tables.get("change_validation_issues")
        if tbl is None or not change_ids or "extra_cost" not in tbl.c \
                or "cost_bearer" not in tbl.c:
            return out
        quoted = (tbl.c.fix_quoted_at.is_not(None) if "fix_quoted_at" in tbl.c
                  else sa_false())
        rows = (await session.execute(
            select(tbl.c.change_id, tbl.c.cost_bearer, tbl.c.extra_cost, quoted)
            .where(tbl.c.change_id.in_(change_ids),
                   tbl.c.extra_cost.is_not(None)))).all()
        for cid, bearer, amount, is_quoted in rows:
            bucket = out.setdefault(cid, {"internal": 0.0, "supplier": 0.0,
                                          "customer": 0.0, "customer_quoted": 0.0,
                                          "count": 0})
            key = bearer if bearer in ("supplier", "customer") else "internal"
            bucket[key] += float(amount or 0.0)
            if key == "customer" and is_quoted:
                # billed to the customer once Sales quoted the fix: revenue
                bucket["customer_quoted"] += float(amount or 0.0)
            bucket["count"] += 1
        return out

    @staticmethod
    async def actual_cost_sums(session, change_ids: list[int]) -> dict[int, dict]:
        from app.models.change_actual_cost import ChangeActualCost
        out: dict[int, dict] = {}
        if not change_ids:
            return out
        rows = (await session.execute(
            select(ChangeActualCost.change_id, ChangeActualCost.category,
                   func.coalesce(func.sum(ChangeActualCost.amount), 0.0))
            .where(ChangeActualCost.change_id.in_(change_ids))
            .group_by(ChangeActualCost.change_id, ChangeActualCost.category))).all()
        for cid, cat, amount in rows:
            bucket = out.setdefault(cid, {"external": 0.0, "scrap": 0.0, "other": 0.0})
            bucket[cat if cat in bucket else "other"] += float(amount or 0.0)
        return out

    @staticmethod
    async def timing(session, change, quote_finish: Optional[str] = None) -> dict:
        """Baseline against forecast (or actual) finish of the detailed plan,
        the slip counted in the plan's own units (working or calendar days).
        Without a detailed baseline the offered (quote plan) finish is the
        baseline: that is the date the customer was told."""
        from app.services.change_plan_service import ChangePlanService
        cal = ChangePlanService.calendar(change, "detailed")
        tasks = [t for t in await ChangePlanService.tasks(session, change, "detailed")
                 if not t.is_idea]
        parents = {t.parent_id for t in tasks if t.parent_id is not None}
        leaves = [t for t in tasks if t.id not in parents]
        baseline = max((t.baseline_finish for t in tasks if t.baseline_finish),
                       default=None)
        source = "detailed_baseline"
        if baseline is None and quote_finish:
            baseline = date.fromisoformat(quote_finish)
            source = "offer"
        if baseline is None:
            quote = await PnlService._plan_finish(session, change, "quote")
            if quote is not None:
                baseline, source = quote, "quote_plan"
        forecast = max((t.end_date for t in tasks), default=None)
        actual = None
        if leaves and all(t.actual_finish for t in leaves):
            # actual_finish is the last worked day: exclusive like the rest
            actual = max(t.actual_finish for t in leaves) + timedelta(days=1)
        against = actual or forecast
        slip = (cal.idx(against) - cal.idx(baseline)
                if baseline is not None and against is not None else None)

        def last(d):
            return (d - timedelta(days=1)).isoformat() if d else None
        return {
            "baseline_finish": last(baseline), "forecast_finish": last(forecast),
            "actual_finish": last(actual), "slip_days": slip,
            "unit": "working days" if cal.working else "calendar days",
            "baseline_source": source if baseline is not None else None,
        }

    @staticmethod
    async def offer_vs_actual(session: AsyncSession, change) -> dict:
        from app.services.offer_service import SNAPSHOT_KEY
        warnings: list[str] = []
        basis, offer = await PnlService._basis_offer(session, change)
        frozen = None
        if offer is not None and offer.status == "accepted":
            frozen = ((offer.data or {}).get(SNAPSHOT_KEY) or {}).get("pnl")
        elif basis == "internal_approval":
            frozen = (await PnlService.internal_frozen(session, [change.id])).get(change.id)
        if basis == "none":
            # Mother plant: nothing was offered or costed here, so there is
            # no plan side; the card shows the actual local costs only.
            planned = {"revenue": None, "internal": 0.0, "external": 0.0,
                       "scrap": 0.0, "currency": "EUR"}
            from app.services import mother_plants as mp
            warnings.append(f"Change from {mp.plant_name(change)}: no offer, "
                            "actual local costs only")
        elif frozen:
            planned = frozen
        else:
            planned = await PnlService.planned_figures(session, change, offer)
            if basis == "accepted_offer":
                warnings.append("The plan was not frozen at acceptance: "
                                "planned costs are the current costing")
                basis = "costing"
        if basis == "costing" and offer is None:
            warnings.append("No accepted offer: revenue is the quoted price")
        elif basis == "sent_offer":
            warnings.append(f"Offer v{offer.version} is not accepted yet")

        actuals = await PnlService.change_actuals(session, change)
        if actuals["unrated_hours"]:
            warnings.append("Hours booked without a department rate are "
                            "counted at zero")
        costs = (await PnlService.actual_cost_sums(session, [change.id])).get(
            change.id, {"external": 0.0, "scrap": 0.0, "other": 0.0})
        issues = (await PnlService.issue_costs(session, [change.id])).get(
            change.id, {"internal": 0.0, "supplier": 0.0, "customer": 0.0,
                        "customer_quoted": 0.0, "count": 0})
        supplement = issues.get("customer_quoted", 0.0)
        if issues["customer"] - supplement > 0.004:
            warnings.append("Customer-borne issue costs are not quoted yet")
        recorded = bool(actuals["total_booked_hours"] or any(costs.values())
                        or issues["count"])
        # the list's phase rule (pnl_phase): no actual before anything is
        # recorded, a zero would read as a saving
        phase = pnl_phase(change, recorded)
        if change.status in ACTUAL_STATUSES and not recorded:
            warnings.append("No actuals recorded yet: no hours booked, no "
                            "invoice or issue cost entered")
        elif phase == "actual" and not costs["external"] and (planned.get("external") or 0) > 0:
            warnings.append("No supplier invoice entered yet")

        planned_revenue = planned.get("revenue")
        figures = compose(
            {"revenue": planned_revenue, "internal": planned.get("internal"),
             "external": planned.get("external"), "scrap": planned.get("scrap")},
            {"revenue": (None if planned_revenue is None
                         else planned_revenue + supplement),
             "internal": actuals["total_actual"], "external": costs["external"],
             "scrap": costs["scrap"], "other": costs["other"],
             "issues_internal": issues["internal"],
             "issues_supplier": issues["supplier"],
             "issues_customer": issues["customer"]},
            in_progress=change.status in IN_PROGRESS_STATUSES)
        if planned_revenue is None and basis != "none":
            warnings.append("No price yet: margins cannot be computed")

        timing = await PnlService.timing(session, change, planned.get("quote_finish"))
        if timing["baseline_finish"] is None:
            warnings.append("No timing baseline")

        # Currencies are compared, never converted (spec §15 phase 2). The
        # revenue is in the offer's currency, every cost line in the
        # costing's; when they differ there is no margin and no margin
        # variance (the /pnl list does the same), only the lines.
        from app.services import costing_rates
        cost_currency = (planned.get("costing_currency")
                         or await costing_rates.costing_currency(session, change))
        # a mother-plant change has no offer: nothing is in another currency
        plan_currency = (cost_currency if basis == "none"
                         else planned.get("currency") or "EUR")
        comparable = cost_currency == plan_currency
        if not comparable:
            warnings.append(
                f"The revenue is in {plan_currency}, the costing in {cost_currency}: "
                "no margin without a currency conversion")
            for k in ("planned_margin", "actual_margin", "forecast_margin",
                      "planned_margin_pct", "actual_margin_pct",
                      "forecast_margin_pct", "variance"):
                figures[k] = None
            figures["margin_row"] = {k: None for k in figures["margin_row"]}
        for line in figures["lines"]:
            line["currency"] = (plan_currency if line["kind"] == "revenue"
                                else cost_currency)
        if actuals.get("currency") and actuals["currency"] != plan_currency \
                and actuals["currency"] != cost_currency and basis != "none":
            warnings.append(
                f"Actual hours are priced in {actuals['currency']}, the plan is in "
                f"{plan_currency}: not converted")
        if actuals.get("other_currency"):
            warnings.append(
                "Booked amounts in " + ", ".join(actuals["other_currency"])
                + " are not in the actual cost (no conversion)")
        if basis != "none":
            outdated = await costing_rates.version_warning(session, change)
            if outdated:
                warnings.append(outdated)
        return {
            # `currency` is the revenue's (the offer's), kept under its old
            # name; cost lines are in costing_currency, each line names its own.
            "change_id": change.id, "currency": plan_currency,
            "revenue_currency": plan_currency,
            "costing_currency": cost_currency,
            "currency_mismatch": not comparable,
            "actual_currency": actuals.get("currency"),
            "basis": basis, "phase": phase,
            "offer_version": planned.get("offer_version"),
            "frozen_at": planned.get("taken_at") if frozen else None,
            **figures,
            "booked_hours": actuals["total_booked_hours"],
            "recorded": recorded,
            "issue_count": issues["count"],
            "timing": timing,
            "piece_price": planned.get("piece_price"),
            "warnings": warnings,
        }


ACTUAL_STATUSES = ("in_implementation", "in_validation", "released", "closed")
# until release, open cost lines are forecast at plan
IN_PROGRESS_STATUSES = ("in_implementation", "in_validation")


def pnl_phase(change, recorded: bool) -> str:
    """'actual' once the change is being implemented AND something was
    recorded (hours, an invoice, an issue cost), else 'plan'. One rule for
    the list and the card."""
    return "actual" if change.status in ACTUAL_STATUSES and recorded else "plan"


def pnl_basis(change, offer, frozen: bool) -> str:
    """What the plan side stands on. One rule for the list and the card:
    none (mother plant, spec §14), accepted_offer (frozen at acceptance),
    costing (accepted but never frozen: planned costs are the current
    costing; or nothing offered yet), sent_offer, internal_approval."""
    from app.services import mother_plants as mp
    if mp.is_mother_plant(change):
        return "none"
    if offer is not None:
        if offer.status == "accepted":
            return "accepted_offer" if frozen else "costing"
        return "sent_offer"
    if not change.customer_relevant and change.internal_approved_amount is not None:
        return "internal_approval"
    return "costing"

LINE_LABELS = (
    ("revenue", "Revenue (offer)", "revenue"),
    ("internal", "Internal effort (hours x rate)", "cost"),
    ("external", "External (supplier)", "cost"),
    ("scrap", "Scrap", "cost"),
    ("other", "Other costs", "cost"),
    ("issues_internal", "Validation issues, borne by us", "cost"),
    ("issues_customer", "Validation issues, billed to customer", "cost"),
    ("issues_supplier", "Validation issues, recoverable from supplier", "info"),
)


def _num_or_none(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compose(planned: dict, actual: dict, *, in_progress: bool = False) -> dict:
    """Lines, margins and the variance from plan and actual figures. Pure, so
    the list and the card count the same way. Costs in `info` lines are
    shown but stay out of the margin (a supplier's recoverable fix).

    While the change is still running (in_progress) a cost line that has not
    reached its plan yet is not a saving: its forecast is the plan, so the
    forecast margin and the variance only move on overruns. After release the
    forecast is the actual."""
    lines = []
    for key, label, kind in LINE_LABELS:
        p = planned.get(key)
        p = 0.0 if p is None and key != "revenue" else p
        a = actual.get(key) or 0.0
        if key in ("other",) and not a and not p:
            continue
        f = max(a, p or 0.0) if in_progress and kind == "cost" else a
        lines.append({"key": key, "label": label, "kind": kind,
                      "planned": _round(p), "actual": _round(a),
                      "forecast": _round(f),
                      "variance": _round(f - (p or 0.0)),
                      "in_margin": kind != "info"})
    cost_p = sum(l["planned"] or 0.0 for l in lines if l["kind"] == "cost")
    cost_a = sum(l["actual"] or 0.0 for l in lines if l["kind"] == "cost")
    cost_f = sum(l["forecast"] or 0.0 for l in lines if l["kind"] == "cost")
    rev_p = planned.get("revenue")
    rev_a = actual.get("revenue") if rev_p is not None else None
    pm = None if rev_p is None else rev_p - cost_p
    am = None if rev_a is None else rev_a - cost_a
    fm = None if rev_a is None else rev_a - cost_f
    pm_pct = _round(pm / rev_p * 100) if pm is not None and rev_p else None
    am_pct = _round(am / rev_a * 100) if am is not None and rev_a else None
    fm_pct = _round(fm / rev_a * 100) if fm is not None and rev_a else None
    return {
        # the margin row, each column its own field: actual = to date,
        # forecast = at completion (open lines at plan while in progress)
        "margin_row": {"planned": _round(pm), "actual": _round(am),
                       "forecast": _round(fm),
                       "planned_pct": pm_pct, "actual_pct": am_pct,
                       "forecast_pct": fm_pct,
                       "variance": (_round(fm - pm)
                                    if fm is not None and pm is not None else None)},
        "lines": lines, "in_progress": in_progress,
        "planned_revenue": _round(rev_p), "actual_revenue": _round(rev_a),
        "planned_cost": _round(cost_p), "actual_cost": _round(cost_a),
        "forecast_cost": _round(cost_f),
        "planned_margin": _round(pm), "actual_margin": _round(am),
        "forecast_margin": _round(fm),
        "planned_margin_pct": _round(pm / rev_p * 100) if pm is not None and rev_p else None,
        "actual_margin_pct": _round(am / rev_a * 100) if am is not None and rev_a else None,
        "forecast_margin_pct": _round(fm / rev_a * 100) if fm is not None and rev_a else None,
        "variance": _round(fm - pm) if fm is not None and pm is not None else None,
    }


# ----------------------------------------------------------------------
# Actual costs that are not hours (supplier invoice lines, scrap, other)
# ----------------------------------------------------------------------
ACTUAL_COST_WINDOW = ("approved", "in_implementation", "in_validation", "released")
# change_actual_costs.amount is Numeric(12, 2)
MAX_ACTUAL_COST = 9_999_999_999.99


class ActualCostError(ValueError):
    """Refused actual-cost write; mapped to HTTP 400."""


class ActualCostForbidden(PermissionError):
    """Mapped to HTTP 403."""


class ActualCostService:

    @staticmethod
    async def is_cost_role(session, change, user) -> bool:
        from app.services.negotiation_service import NegotiationService
        return await NegotiationService.may_read(session, change, user)

    @staticmethod
    async def own_department_ids(session, user) -> set[int]:
        from app.services.workflow_service import WorkflowService
        return set(await WorkflowService.effective_department_ids(session, user))

    @staticmethod
    async def list_costs(session, change, user) -> dict:
        """Cost roles read every line; anyone else (a member of a department
        that may enter costs) reads only the lines they entered themselves,
        never a colleague's or another department's amounts."""
        from app.models.change_actual_cost import ChangeActualCost
        from app.models.workflow import Department
        cost_role = await ActualCostService.is_cost_role(session, change, user)
        own = set() if cost_role else await ActualCostService.own_department_ids(
            session, user)
        rows = list((await session.execute(
            select(ChangeActualCost).where(ChangeActualCost.change_id == change.id)
            .order_by(ChangeActualCost.cost_date.desc(), ChangeActualCost.id.desc())
        )).scalars().all())
        if not cost_role:
            rows = [r for r in rows if r.created_by == user.id]
        names = dict((await session.execute(select(Department.id, Department.name))).all())
        users = dict((await session.execute(
            select(User.id, User.full_name).where(
                User.id.in_({r.created_by for r in rows} or {0})))).all())
        in_window = change.status in ACTUAL_COST_WINDOW
        items = [{
            "id": r.id, "change_id": r.change_id,
            "department_id": r.department_id,
            "department_name": names.get(r.department_id),
            "category": r.category, "vendor_name": r.vendor_name,
            "amount": _round(r.amount), "cost_date": r.cost_date,
            "note": r.note, "attachment_id": r.attachment_id,
            "created_by": r.created_by, "created_by_name": users.get(r.created_by),
            "created_at": r.created_at,
            "can_delete": in_window and (cost_role or r.created_by == user.id),
        } for r in rows]
        return {
            "items": items,
            "total": _round(sum(i["amount"] or 0.0 for i in items)),
            "can_write": in_window and (cost_role or bool(own)),
            # None = any department (cost roles), else only these
            "writable_department_ids": None if cost_role else sorted(own),
            "cost_role": cost_role,
        }

    @staticmethod
    async def add(session, change, user, *, category: str, amount: float,
                  cost_date: date, department_id: Optional[int] = None,
                  vendor_name: Optional[str] = None, note: Optional[str] = None,
                  attachment_id: Optional[int] = None):
        from app.models.change_actual_cost import (
            ACTUAL_COST_CATEGORIES, ChangeActualCost,
        )
        from app.models.workflow import Department
        from app.services.change_service import ChangeService
        if change.status not in ACTUAL_COST_WINDOW:
            raise ActualCostError(
                "Actual costs are entered from approval until release")
        if category not in ACTUAL_COST_CATEGORIES:
            raise ActualCostError(
                f"Unknown category '{category}' - one of external, scrap, other")
        if amount is None or amount <= 0:
            raise ActualCostError("The amount must be greater than zero")
        if amount > MAX_ACTUAL_COST:
            raise ActualCostError(
                f"The amount is at most {MAX_ACTUAL_COST:,.2f}")
        if department_id is not None and await session.get(Department, department_id) is None:
            raise ActualCostError("Unknown department")
        if attachment_id is not None:
            from app.models.change import ChangeAttachment
            att = await session.get(ChangeAttachment, attachment_id)
            if att is None or att.change_id != change.id:
                raise ActualCostError("That attachment is not on this change")
        if not await ActualCostService.is_cost_role(session, change, user):
            own = await ActualCostService.own_department_ids(session, user)
            if department_id is None or department_id not in own:
                raise ActualCostForbidden(
                    "Only Project Management, Sales, the change lead, an admin "
                    "or a member of the named department may enter its costs")
        row = ChangeActualCost(
            change_id=change.id, department_id=department_id, category=category,
            vendor_name=(vendor_name or "").strip()[:120] or None,
            amount=round(float(amount), 2), cost_date=cost_date,
            note=(note or "").strip() or None, attachment_id=attachment_id,
            created_by=user.id)
        session.add(row)
        await session.flush()
        # No amount in the changelog: everybody on the change reads it.
        await ChangeService.append_changelog(
            session, change, "actual_cost_added",
            f"Actual cost entered ({category}"
            + (f", {row.vendor_name}" if row.vendor_name else "") + ")",
            user.id, new_value={"actual_cost_id": row.id, "category": category})
        return row

    @staticmethod
    async def delete(session, change, user, cost_id: int) -> None:
        from app.models.change_actual_cost import ChangeActualCost
        from app.services.change_service import ChangeService
        row = await session.get(ChangeActualCost, cost_id)
        if row is None or row.change_id != change.id:
            raise LookupError("Actual cost not found on this change")
        if change.status not in ACTUAL_COST_WINDOW:
            raise ActualCostError(
                "Actual costs are changed from approval until release")
        if not (row.created_by == user.id
                or await ActualCostService.is_cost_role(session, change, user)):
            raise ActualCostForbidden(
                "Only whoever entered it or the cost roles may delete it")
        await session.delete(row)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "actual_cost_deleted",
            f"Actual cost removed ({row.category})", user.id,
            old_value={"actual_cost_id": cost_id, "category": row.category})
