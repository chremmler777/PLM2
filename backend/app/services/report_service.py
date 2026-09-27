"""Live SQL aggregates for the reports/analytics surface: pipeline funnel +
throughput + cycle time, department/owner workload, and cost roll-ups.

All three entry points are org-scoped through Task 13's `_org_scope` (which
now also bypasses scoping entirely for admin viewers - see change_service.py)
and are designed to return zero-filled, division-by-zero-safe shapes even
against an empty database.
"""
import json
from collections import defaultdict
from datetime import datetime
from statistics import mean
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest, CHANGE_STATUSES, TERMINAL_STATUSES
from app.models.entities import AuditLog, Plant, Project, User
from app.services.change_service import ChangeService, _org_scope

TRANSITION_ACTIONS = ("status_changed", "deviated_transition")


class ReportService:

    @staticmethod
    async def pipeline(session: AsyncSession, viewer: Optional[User]) -> dict:
        # --- funnel: count of changes per status, zero-filled ---
        counts = dict.fromkeys(CHANGE_STATUSES, 0)
        rows = (await session.execute(_org_scope(
            select(ChangeRequest.status, func.count()).group_by(ChangeRequest.status),
            viewer,
        ))).all()
        for status, cnt in rows:
            counts[status] = cnt
        funnel = [{"status": s, "count": counts[s]} for s in CHANGE_STATUSES]

        # --- throughput: released changes per month, last 12 months ---
        released_dates = (await session.execute(_org_scope(
            select(ChangeRequest.released_at).where(ChangeRequest.released_at.is_not(None)),
            viewer,
        ))).scalars().all()
        by_month: dict[str, int] = defaultdict(int)
        for d in released_dates:
            by_month[f"{d.year:04d}-{d.month:02d}"] += 1

        now = datetime.utcnow()
        months = []
        y, m = now.year, now.month
        for i in range(11, -1, -1):
            mm = m - i
            yy = y
            while mm <= 0:
                mm += 12
                yy -= 1
            months.append(f"{yy:04d}-{mm:02d}")
        throughput = [{"month": mk, "released": by_month.get(mk, 0)} for mk in months]

        # --- avg_stage_days: consecutive status_changed/deviated_transition
        # AuditLog rows per change. Each row's own (old_value, new_value) is
        # the pair label; the duration attributed to that pair is the time
        # until the *next* transition on the same change (i.e. how long the
        # change stayed in `new_value` before moving on). A change's most
        # recent transition contributes no duration (still in that stage). ---
        numbers = (await session.execute(_org_scope(
            select(ChangeRequest.change_number), viewer))).scalars().all()
        pair_deltas: dict[tuple, list[float]] = defaultdict(list)
        if numbers:
            audit_rows = (await session.execute(
                select(AuditLog)
                .where(AuditLog.correlation_id.in_(numbers),
                       AuditLog.action.in_(TRANSITION_ACTIONS))
                .order_by(AuditLog.correlation_id, AuditLog.timestamp)
            )).scalars().all()
            by_change: dict[str, list[AuditLog]] = defaultdict(list)
            for row in audit_rows:
                by_change[row.correlation_id].append(row)
            for entries in by_change.values():
                for i in range(len(entries) - 1):
                    cur, nxt = entries[i], entries[i + 1]
                    old_v = json.loads(cur.old_values) if cur.old_values else None
                    new_v = json.loads(cur.new_values) if cur.new_values else None
                    delta_days = (nxt.timestamp - cur.timestamp).total_seconds() / 86400.0
                    pair_deltas[(old_v, new_v)].append(delta_days)
        avg_stage_days = [
            {"from_status": frm, "to_status": to, "avg_days": mean(deltas)}
            for (frm, to), deltas in pair_deltas.items()
        ]

        # --- on_time_rate: released/closed changes with a required_by_date ---
        eligible = (await session.execute(_org_scope(
            select(ChangeRequest).where(
                ChangeRequest.required_by_date.is_not(None),
                ChangeRequest.status.in_(("released", "closed")),
            ), viewer,
        ))).scalars().all()
        on_time_rate = None
        if eligible:
            on_time = 0
            for c in eligible:
                completed = c.released_at or c.closed_at
                if completed is not None and completed <= c.required_by_date:
                    on_time += 1
            on_time_rate = on_time / len(eligible)

        return {
            "funnel": funnel,
            "throughput": throughput,
            "avg_stage_days": avg_stage_days,
            "on_time_rate": on_time_rate,
        }

    @staticmethod
    async def workload(session: AsyncSession, viewer: Optional[User]) -> dict:
        from app.models.part import PartRevision
        from app.models.workflow import Department, WfInstance, WfInstanceTask

        now = datetime.utcnow()

        change_ids = set((await session.execute(_org_scope(
            select(ChangeRequest.id), viewer))).scalars().all())

        dept_agg: dict[int, dict] = {}
        owner_agg: dict[int, dict] = {}
        escalation_count = 0

        if change_ids:
            # Task-based counts are the workload source of truth: every
            # engine-managed piece of work now runs through WfInstanceTask,
            # via either a change-scoped instance (WfInstance.change_id) or a
            # part-revision instance spawned off the change's ECN revisions
            # (PartRevision.originating_change_id). Legacy ChangeAssessment
            # rows with no linked wf_instance_task_id are pre-engine data and
            # are deliberately excluded here rather than double-counted.
            rows_by_change = (await session.execute(
                select(WfInstanceTask, Department.name)
                .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
                .join(Department, Department.id == WfInstanceTask.department_id)
                .where(WfInstance.change_id.in_(change_ids),
                       WfInstance.status == "active",
                       WfInstanceTask.status == "active")
            )).all()
            rows_by_revision = (await session.execute(
                select(WfInstanceTask, Department.name)
                .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
                .join(PartRevision, PartRevision.id == WfInstance.part_revision_id)
                .join(Department, Department.id == WfInstanceTask.department_id)
                .where(PartRevision.originating_change_id.in_(change_ids),
                       WfInstance.status == "active",
                       WfInstanceTask.status == "active")
            )).all()

            seen_task_ids: set[int] = set()
            for task, dept_name in (*rows_by_change, *rows_by_revision):
                if task.id in seen_task_ids:
                    continue
                seen_task_ids.add(task.id)
                overdue = task.due_date is not None and task.due_date < now

                d = dept_agg.setdefault(task.department_id, {
                    "department_id": task.department_id, "name": dept_name,
                    "open": 0, "overdue": 0,
                })
                d["open"] += 1
                if overdue:
                    d["overdue"] += 1
                    escalation_count += 1

                if task.owner_id is not None:
                    o = owner_agg.setdefault(task.owner_id, {
                        "owner_id": task.owner_id, "owner_name": task.owner_name,
                        "open": 0, "overdue": 0,
                    })
                    o["open"] += 1
                    if overdue:
                        o["overdue"] += 1

        # --- at-risk changes: the phase's ACTIVE deadline at risk/overdue
        # (quote deadline pre-quote, release deadline post-acceptance). No
        # required_by_date filter: deadline_state returns None on its own when
        # no deadline is active.
        candidates = (await session.execute(_org_scope(
            select(ChangeRequest).where(
                ChangeRequest.status.not_in(TERMINAL_STATUSES),
            ), viewer,
        ))).scalars().all()
        at_risk_changes = []
        for c in candidates:
            state = await ChangeService.deadline_state(session, c)
            if state in ("at_risk", "overdue"):
                due = (c.release_due_date if c.active_deadline == "release"
                       else c.required_by_date)
                at_risk_changes.append({
                    "id": c.id, "change_number": c.change_number, "title": c.title,
                    # key kept for the existing card; value is the active
                    # deadline's date, whichever kind that is.
                    "required_by_date": due.isoformat(),
                    "state": state,
                })

        return {
            "departments": list(dept_agg.values()),
            "owners": list(owner_agg.values()),
            "at_risk_changes": at_risk_changes,
            "escalation_count": escalation_count,
        }

    @staticmethod
    async def cost(session: AsyncSession, viewer: Optional[User]) -> dict:
        from app.services.pnl_service import PnlService
        from app.services.price_redaction import price_scope

        # Budgets and costs are money: only the changes whose prices the
        # viewer may read (price_redaction.price_scope) are rolled up.
        async def _scope(stmt):
            return await price_scope(session, viewer, _org_scope(stmt, viewer))

        budget_rows = (await session.execute(await _scope(
            select(ChangeRequest.project_id, func.sum(ChangeRequest.estimated_cost))
            .group_by(ChangeRequest.project_id),
        ))).all()

        # Same cost basis as the P&L list (PnlService.changes_pnl): assessment
        # cost lines plus costing positions, in the costing currency, never
        # summed across currencies. cost_basis_by_currency is the P&L's own
        # helper, so this report and the P&L can never disagree about what a
        # change costs.
        changes = (await session.execute(await _scope(select(ChangeRequest)))).scalars().all()
        basis, plant_of = await PnlService.cost_basis_by_currency(session, changes)

        project_of = {c.id: c.project_id for c in changes}
        project_ids = {pid for pid, _ in budget_rows if pid is not None} \
            | {project_of[cid] for cid in basis if project_of.get(cid) is not None}
        names: dict[int, str] = {}
        if project_ids:
            names = dict((await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )).all())

        # --- projects ---
        merged: dict[int, dict] = {}
        for pid, budget in budget_rows:
            if pid is None:
                continue
            merged.setdefault(pid, {"project_id": pid, "name": names.get(pid, ""),
                                     "budget": 0.0, "actual": 0.0, "currency": None,
                                     "actual_by_currency": {}, "mixed_currency": False})
            merged[pid]["budget"] = budget or 0.0
        for cid, by_cur in basis.items():
            pid = project_of.get(cid)
            if pid is None:
                continue
            row = merged.setdefault(pid, {"project_id": pid, "name": names.get(pid, ""),
                                          "budget": 0.0, "actual": 0.0, "currency": None,
                                          "actual_by_currency": {}, "mixed_currency": False})
            for cur, (internal, external) in by_cur.items():
                row["actual_by_currency"][cur] = (
                    row["actual_by_currency"].get(cur, 0.0) + (internal or 0.0) + (external or 0.0))
        for row in merged.values():
            ReportService._finish_actual(row)
        projects = list(merged.values())

        # --- plants: attributed to each change's costing plant (the same
        # plant the P&L prices it at - PnlService._portfolio_context), not
        # to a cost line's own plant_id as before. A costing position has no
        # plant of its own, so once positions are part of the basis there is
        # no per-line plant left to attribute them to; the costing plant is
        # the one place both cost lines and positions agree on. ---
        plant_merged: dict[int, dict] = {}
        for cid, by_cur in basis.items():
            pid = plant_of.get(cid)
            if pid is None:
                continue
            row = plant_merged.setdefault(pid, {"plant_id": pid, "name": "",
                                                "actual": 0.0, "currency": None,
                                                "actual_by_currency": {}, "mixed_currency": False})
            for cur, (internal, external) in by_cur.items():
                row["actual_by_currency"][cur] = (
                    row["actual_by_currency"].get(cur, 0.0) + (internal or 0.0) + (external or 0.0))
        plant_ids = set(plant_merged)
        if plant_ids:
            plant_names = dict((await session.execute(
                select(Plant.id, Plant.name).where(Plant.id.in_(plant_ids))
            )).all())
            for pid, row in plant_merged.items():
                row["name"] = plant_names.get(pid, "")
        for row in plant_merged.values():
            ReportService._finish_actual(row)
        plants = list(plant_merged.values())

        return {"projects": projects, "plants": plants}

    @staticmethod
    def _finish_actual(row: dict) -> None:
        """Fill `actual`/`currency` from `actual_by_currency`: the single
        number and its currency when there is only one, else the largest
        currency's total (best-effort, for callers still reading the old
        scalar field) with `mixed_currency` raised so a caller that cares
        can fall back to the accurate `actual_by_currency` breakdown."""
        by_cur = row["actual_by_currency"]
        if not by_cur:
            return
        row["mixed_currency"] = len(by_cur) > 1
        primary = max(by_cur, key=lambda c: abs(by_cur[c]))
        row["currency"] = primary
        row["actual"] = by_cur[primary]
